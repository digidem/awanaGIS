"""Run a fresh QGIS project and backend through the normal agent request path."""
import configparser
from hashlib import sha256
import importlib
import sys
import threading
import time
from pathlib import Path
from urllib.parse import unquote, urlparse

from qgis.analysis import QgsNativeAlgorithms
from qgis.core import Qgis, QgsApplication, QgsProject, QgsRectangle
from qgis.gui import QgsLayerTreeMapCanvasBridge, QgsMapCanvas
from qgis.PyQt.QtCore import QCoreApplication

from ...backends import build_backend
from ...config import DEFAULTS
from ...core.executor import MainThreadExecutor
from ...core.toolkit import QgisToolkit
from .trace import artifacts_under, event_record, pdf_exports, redact, smp_export_seconds, write_trace


class EvalConfig:
    def __init__(self, provider, model):
        self.values = dict(DEFAULTS, provider=provider, model=model, connection_mode='api_key',
                           external_access_always_allowed=False)

    def get(self, name, default=None):
        return self.values.get(name, default)


class EvalIface:
    """Small canvas-bearing interface; desktop-only interactions need acceptance testing."""
    def __init__(self, project):
        self.canvas = QgsMapCanvas()
        self.active_layer = None
        self.canvas.resize(1024, 768)
        self.canvas.setDestinationCrs(project.crs())
        self.bridge = QgsLayerTreeMapCanvasBridge(project.layerTreeRoot(), self.canvas)
        self.bridge.setCanvasLayers()
        self.canvas.setExtent(project.viewSettings().defaultViewExtent())

    def mapCanvas(self):
        return self.canvas

    def activeLayer(self):
        layers = self.canvas.layers()
        return self.active_layer if self.active_layer in layers else (layers[0] if layers else None)


class EvalToolkit(QgisToolkit):
    """Approve the run's own files; leave other permissions to the normal gate.

    An unattended run stands in for a user who approves operations on the
    files they supplied and on the results folder the runner names in the
    first prompt. URLs, network, subprocess and environment access, and any
    absolute path outside the run directory still go through the normal
    permission prompt, which unattended runs deny.
    """
    _NETWORK_MARKERS = (
        'urllib', 'requests', 'socket.', 'http.client', 'httpx', 'aiohttp', 'ftplib', 'smtplib',
        'websocket', 'subprocess', 'os.system', 'popen', 'webbrowser',
        'qgsnetworkaccessmanager', 'qgsfiledownloader', 'qgsnetworkrequest', 'qgsblockingnetworkrequest',
    )

    def __init__(self, iface, config, input_dir, capture_first_pdf=False):
        super().__init__(iface, config=config)
        self.input_dir = Path(input_dir).resolve()
        self.output_dir = self.input_dir.parent / 'outputs'
        self.capture_first_pdf = capture_first_pdf
        self.first_pdf_export = None

    def export_layout(self, layout_id, output_path, format="pdf"):
        output_dir = self.output_dir
        capture = self.capture_first_pdf and self.first_pdf_export is None
        earlier_pdf = capture and any(path.lower().endswith('.pdf') for path in artifacts_under(output_dir))
        result = super().export_layout(layout_id, output_path, format)
        if not capture or earlier_pdf or not result.get('ok'):
            return result
        output = Path(result['output_path']).resolve()
        if result.get('format') != 'pdf' or not output.is_relative_to(output_dir):
            return result
        from qgis.core import QgsLayoutItemLegend, QgsLayoutItemMap, QgsLayoutItemScaleBar

        layout = QgsProject.instance().layoutManager().layoutByName(layout_id.strip())
        items = layout.items()
        self.first_pdf_export = {
            'output': redact(str(output.relative_to(output_dir))),
            'sha256': sha256(output.read_bytes()).hexdigest(),
            'map_layer_ids': [[layer.id() for layer in item.layersToRender()] for item in items
                              if isinstance(item, QgsLayoutItemMap)],
            'has_scale_bar': any(isinstance(item, QgsLayoutItemScaleBar) for item in items),
            'has_legend': any(isinstance(item, QgsLayoutItemLegend) for item in items),
        }
        return result

    def _inside_run(self, value):
        """True for an absolute path that resolves inside the run directory."""
        return Path(value).is_absolute() and Path(value).resolve().is_relative_to(self.input_dir.parent)

    @staticmethod
    def _local_path(uri):
        """Return the filesystem path of a layer URI, or None when it is not a local file."""
        if not isinstance(uri, str) or not uri.strip():
            return None
        text = uri.strip()
        if text.casefold().startswith('file://'):
            return Path(unquote(urlparse(text).path))
        if '://' in text.casefold():
            return None
        return Path(text.split('?', 1)[0].split('|', 1)[0])

    def _non_local_reason(self, code):
        """Describe what model-authored code reaches beyond the run directory, or None when it does not.

        Relative file names are left to the code: the working directory is
        the read-only checkout, so they cannot name user data.
        """
        lowered = code.casefold()
        if 'environ' in lowered or 'getenv' in lowered:
            return 'read environment variables'
        if '://' in lowered or any(marker in lowered for marker in self._NETWORK_MARKERS):
            return 'reach the network or start processes'
        for match in self._STRING_LITERAL_RE.finditer(code):
            value = match.group('value')
            if (self._looks_external_reference(value) and self._PATH_RE.search(value)
                    and not self._inside_run(value)):
                return f'access a path outside the run directory: {value}'
        return None

    def confirm_external_access(self, tool_name, args):
        args = args or {}
        if tool_name == 'add_layer':
            path = self._local_path(args.get('uri'))
            if path is not None and self._inside_run(str(path)):
                return None
        if tool_name == 'run_processing':
            flagged = [value for value in self._iter_strings(args.get('params') or {})
                       if self._looks_external_reference(value)]
            if all(self._inside_run(value) for value in flagged):
                return None
        if tool_name == 'run_pyqgis':
            reason = self._non_local_reason(str(args.get('code') or ''))
            if reason is None:
                return None
            verdict = super().confirm_external_access(tool_name, args)
            if verdict is None:
                # The normal gate does not watch environment access, and an
                # unattended worker holds the eval credential in its environment.
                return {'ok': False, 'error': f'Permission denied: {reason}', 'cancelled': True}
            return verdict
        return super().confirm_external_access(tool_name, args)


def layer_for_file(project, path):
    """Return the project layer whose source is the given file."""
    target = Path(path).resolve()
    for layer in project.mapLayers().values():
        source = layer.source().split('?', 1)[0].split('|', 1)[0]
        if source and Path(source).resolve() == target:
            return layer
    raise RuntimeError(f'No project layer is backed by {target.name}')


def load_processing_plugin(path, iface):
    """Load an explicitly installed plugin, including its Processing provider."""
    path = Path(path).resolve()
    if not (path / '__init__.py').is_file():
        raise ValueError('Plugin path must be the installed plugin directory')
    sys.path.insert(0, str(path.parent))
    module = importlib.import_module(path.name)
    plugin = module.classFactory(iface)
    plugin.initGui()
    return plugin


def plugin_version(path):
    if not path:
        return None
    metadata = configparser.ConfigParser()
    metadata.read(Path(path) / 'metadata.txt', encoding='utf-8')
    return metadata.get('general', 'version', fallback=None)


def _turn(backend, prompt, history, timeout=300, output_dir=None, questions=None):
    started = time.monotonic()
    events = []
    result = {}
    stop = threading.Event()

    def emit(event):
        events.append(event_record(event, started, output_dir))

    def worker():
        try:
            result['history'] = backend.send(prompt, history, emit, stop.is_set)
        except Exception as exc:
            result['error'] = type(exc).__name__

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    while thread.is_alive():
        QCoreApplication.processEvents()
        thread.join(0.01)
        if time.monotonic() - started > timeout and not stop.is_set():
            stop.set()
            result['error'] = 'Timeout'
    QCoreApplication.processEvents()
    for timestamp, question in questions or []:
        events.append({'type': 'user_question', 'data': {'question': question},
                       'elapsed_seconds': timestamp - started})
    events.sort(key=lambda event: event['elapsed_seconds'])
    reply = ''.join(str(e['data'].get('text', '')) for e in events if e['type'] == 'text')
    turn = {'prompt': prompt, 'reply': reply, 'events': events, 'elapsed_seconds': time.monotonic() - started}
    if any(e['type'] == 'error' for e in events):
        result['error'] = 'BackendError'
    if 'error' in result:
        turn['error'] = result['error']
    return turn, result.get('history', history)


def visible_reply_check(turn, index):
    """Require a visible handoff after the last tool, or a terminal user question."""
    check_id = f'visible_reply_{index + 1}'
    if 'error' in turn:
        return {'id': check_id, 'status': 'blocked', 'detail': 'Turn did not complete'}
    events = turn.get('events', [])
    last_tool = -1
    last_name = None
    for position, event in enumerate(events):
        if event.get('type') in ('tool_use', 'tool_result'):
            last_tool = position
            last_name = event.get('data', {}).get('name')
    final_text = ''.join(str(event.get('data', {}).get('text', ''))
                         for event in events[last_tool + 1:] if event.get('type') == 'text').strip()
    last_use = next((position for position in range(len(events) - 1, -1, -1)
                     if events[position].get('type') == 'tool_use'), -1)
    # The capture callback resolves the fixture prompt without supplying a user answer.
    question = (last_name == 'ask_user' and last_use >= 0
                and events[last_tool].get('data', {}).get('status') != 'error'
                and events[last_use].get('data', {}).get('name') == 'ask_user'
                and any(event.get('type') == 'user_question'
                        for event in events[last_use + 1:last_tool + 1]))
    return {'id': check_id, 'status': 'pass' if final_text or question else 'fail',
            'detail': 'Visible final reply or question' if final_text or question else 'No visible final reply'}


def run_case(case_id, run_dir, provider, model, variant='baseline', backend_factory=None, plugin_path=None):
    """Execute one case; backend_factory(config, toolkit, executor) permits offline tests."""
    from .fixtures import build_fixture
    from .checks import OBSERVED_CASES, evaluate, evaluate_step, observe_run

    app = QgsApplication.instance()
    if app is None:
        app = QgsApplication([], True)
        app.initQgis()
    processing_path = Path(QgsApplication.pkgDataPath()) / 'python' / 'plugins'
    if str(processing_path) not in sys.path:
        sys.path.insert(0, str(processing_path))
    try:
        from processing.core.Processing import Processing
        Processing.initialize()
    except ImportError:
        pass
    processing_registry = QgsApplication.processingRegistry()
    if processing_registry.providerById('native') is None:
        processing_registry.addProvider(QgsNativeAlgorithms())
    run_dir = Path(run_dir).resolve()
    run_dir.mkdir(parents=True, exist_ok=False)
    fixture = build_fixture(case_id, run_dir, variant)
    project = QgsProject.instance()
    project.clear()
    if not project.read(str(fixture.project_path)):
        raise RuntimeError('Unable to load synthetic fixture project')
    config = EvalConfig(provider, model)
    iface = EvalIface(project)
    selected_codes = set(getattr(fixture, 'preselected_codes', ()))
    if selected_codes:
        # Resolve by source file: held-out fixtures name the layer differently.
        layer = layer_for_file(project, fixture.villages_path)
        layer.selectByIds([feature.id() for feature in layer.getFeatures() if str(feature['codigo']) in selected_codes])
        iface.active_layer = layer
    plugin = load_processing_plugin(plugin_path, iface) if plugin_path else None
    executor = MainThreadExecutor(config=config)
    toolkit = EvalToolkit(iface, config, run_dir / 'inputs', capture_first_pdf=case_id == 'pdf_basemap')
    questions = []

    def capture_question(question, options, allow_free_text, request):
        labels = {option.get('label') for option in options if isinstance(option, dict)}
        if not {'Allow once', 'Always allow', 'Deny'}.issubset(labels):
            questions.append((time.monotonic(), redact(str(question))))
        # Unattended runs continue via the fixture's scripted conversation.
        toolkit._resolve_ask_user({'cancelled': True}, request=request)

    toolkit.set_ask_user_emitter(capture_question)
    backend = (backend_factory or build_backend)(config, toolkit, executor)
    trace = {'case': case_id, 'variant': variant, 'backend': {'provider': provider, 'model': model},
             'qgis_version': Qgis.QGIS_VERSION, 'plugin_version': plugin_version(plugin_path),
             'turns': [], 'artifacts': [], 'checks': [], 'status': 'completed',
             'metrics': {'model_requests': None, 'export_seconds': None, 'scripted_wait_seconds': 0.0}}
    history = []
    workflow_steps = ('basemap', 'load', 'style', 'filter_join', 'pdf')
    started = time.monotonic()
    try:
        if case_id.startswith('smp_') and not QgsApplication.processingRegistry().algorithmById(
                'smp:generatesmp'):
            trace['status'] = 'blocked'
            trace['checks'] = [{'id': 'runner', 'status': 'blocked',
                                'detail': 'CoMapeo Map Builder processing algorithm is unavailable'}]
            trace['timing'] = {'elapsed_seconds': time.monotonic() - started}
            write_trace(run_dir / 'run.json', trace)
            return trace
        if backend_factory is None and backend.validate():
            trace['status'] = 'blocked'
            trace['checks'] = [{'id': 'runner', 'status': 'blocked',
                                'detail': 'Backend configuration or credential unavailable'}]
            trace['timing'] = {'elapsed_seconds': time.monotonic() - started}
            write_trace(run_dir / 'run.json', trace)
            return trace
        for index, prompt in enumerate(fixture.turns):
            if prompt.strip().lower().startswith('pronto') and getattr(fixture, 'region_extent', None):
                extent = fixture.region_extent
                iface.canvas.setExtent(QgsRectangle(*extent))
                iface.canvas.refresh()
                QCoreApplication.processEvents()
                actual = iface.canvas.extent()
                trace['canvas_extent_after_pan'] = [actual.xMinimum(), actual.yMinimum(),
                                                    actual.xMaximum(), actual.yMaximum()]
            request = prompt
            if index == 0:
                request += '\n\nPasta para resultados: ' + str(fixture.output_dir)
            if (case_id, index) in {('load', 0), ('workflow', 1)}:
                files = getattr(fixture, 'input_files', ())
                if files:
                    request += '\n\nArquivos fornecidos: ' + ', '.join(map(str, files))
            questions.clear()
            turn, history = _turn(backend, request, history, output_dir=fixture.output_dir.resolve(),
                                  questions=questions)
            turn['prompt'] = prompt
            turn['questions'] = [question for _, question in questions]
            if case_id == 'smp_region' and index == 0:
                turn['artifacts'] = artifacts_under(fixture.output_dir)
            trace['turns'].append(turn)
            if case_id in OBSERVED_CASES:
                # A session case is graded turn by turn: keep what the derived
                # file, its project layers and the workspace state held now.
                turn['observed'] = observe_run(fixture, project, run_dir)
                turn['workspace_state'] = redact(toolkit.agent_state_summary())
            if case_id in ('crs_view', 'selection'):
                bounds = iface.canvas.extent()
                trace['canvas_state_after_turn'] = {
                    'extent': [bounds.xMinimum(), bounds.yMinimum(), bounds.xMaximum(), bounds.yMaximum()],
                    'layer_ids': [layer.id() for layer in iface.canvas.layers()]}
            trace.setdefault('pdf_exports', []).extend(pdf_exports(turn['events']))
            if 'error' in turn:
                break
            if case_id == 'workflow' and index < len(workflow_steps):
                check = evaluate_step(workflow_steps[index], fixture, project, {**trace, 'turns': [turn]})
                trace.setdefault('workflow_checks', []).append(check)
        all_events = [event for turn in trace['turns'] for event in turn['events']]
        trace['metrics']['tool_calls'] = sum(event['type'] == 'tool_use' for event in all_events)
        uses = [e for e in all_events if e['type'] == 'tool_use']
        fingerprints = [(e['data'].get('name'), e['data'].get('args_sha256')) for e in uses]
        trace['metrics']['repeated_tool_calls'] = len(fingerprints) - len(set(fingerprints))
        trace['metrics']['failed_tool_calls'] = sum(
            e['type'] == 'tool_result' and e['data'].get('status') == 'error' for e in all_events)
        first_text = None
        offset = 0.0
        for item in trace['turns']:
            text_times = [e['elapsed_seconds'] for e in item['events']
                          if e['type'] == 'text' and e['data'].get('text')]
            if text_times:
                first_text = offset + min(text_times)
                break
            offset += item['elapsed_seconds']
        trace['metrics']['first_text_seconds'] = first_text
        trace['metrics']['clarification_turns'] = sum(bool(turn['questions']) for turn in trace['turns'])
        trace['timing'] = {'elapsed_seconds': time.monotonic() - started}
        trace['metrics']['elapsed_seconds'] = trace['timing']['elapsed_seconds']
        trace['artifacts'] = artifacts_under(fixture.output_dir)
        trace['metrics']['export_seconds'] = smp_export_seconds(all_events)
        trace['metrics']['smp_bytes'] = sum(
            (fixture.output_dir / path).stat().st_size for path in trace['artifacts'] if path.lower().endswith('.smp')
        ) or None
        if toolkit.first_pdf_export is not None:
            trace['first_pdf_export'] = toolkit.first_pdf_export
        trace['checks'] = evaluate(fixture, project, trace)
        visibility = [visible_reply_check(turn, index) for index, turn in enumerate(trace['turns'])]
        trace['checks'].extend(visibility)
        if case_id == 'workflow':
            aggregate = next((check for check in trace['checks'] if check['id'] == 'workflow'), None)
            if aggregate is not None:
                statuses = {check['status'] for check in visibility} | {aggregate['status']}
                aggregate['status'] = next(status for status in ('fail', 'blocked', 'manual', 'pass')
                                           if status in statuses)
                aggregate['detail'] += ' Includes visible reply checks for completed turns.'
        if any(event['data'].get('permission_denied') for event in all_events):
            trace['checks'].append({'id': 'permission', 'status': 'blocked',
                                    'detail': 'An unattended external-access request was denied'})
        if any('error' in turn for turn in trace['turns']):
            trace['status'] = 'error'
            trace['checks'].append({'id': 'runner', 'status': 'blocked', 'detail': 'Backend raised an exception'})
        write_trace(run_dir / 'run.json', trace)
        return trace
    finally:
        if plugin is not None:
            plugin.unload()
        project.clear()
