"""Offline checks for the QGIS evaluation request path."""
from importlib import import_module
import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from qgis.core import QgsApplication, QgsProject

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
BACKENDS = import_module(f"{ROOT.name}.backends.base")
EVAL_MODULE = f"{ROOT.name}.evals.qgis_agent"
AgentEvent, EventType = BACKENDS.AgentEvent, BACKENDS.EventType
run_case = import_module(f"{EVAL_MODULE}.runner").run_case
trace_module = import_module(f"{EVAL_MODULE}.trace")
event_record, smp_export_seconds = trace_module.event_record, trace_module.smp_export_seconds


class RunnerTest(unittest.TestCase):
    def test_pdf_trace_restricts_linkage_and_redacts_credentials(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            'os.environ', {'EVAL_TEST_API_KEY': 'synthetic-key-that-should-not-appear'}
        ):
            root = Path(directory)
            start = time.monotonic()
            tool_call = AgentEvent(EventType.TOOL_USE, {'name': 'export_layout', 'input': {
                'layout_id': 'Mapa', 'output_path': str(root / 'mapa.pdf'),
            }})
            result = AgentEvent(EventType.TOOL_RESULT, {'name': 'export_layout', 'result': '{"ok":true}'})
            report = [event_record(event, start, root) for event in (tool_call, result)]
            self.assertEqual(trace_module.pdf_exports(report), [{'layout_id': 'Mapa', 'output': 'mapa.pdf'}])
            tool_call.data['input']['output_path'] = str(root.parent / 'outside.pdf')
            self.assertNotIn('pdf_export', event_record(tool_call, start, root)['data'])
            text = AgentEvent(EventType.TEXT, {'text': 'Chave: synthetic-key-that-should-not-appear'})
            self.assertEqual(event_record(text, start, root)['data']['text'], 'Chave: [redacted]')

    def test_smp_timing_records_only_known_export_calls(self):
        start = time.monotonic()
        events = [
            AgentEvent(EventType.TOOL_USE, {'name': 'run_processing', 'input': {'alg_id': 'smp:generatesmp'}}),
            AgentEvent(EventType.TOOL_RESULT, {'name': 'run_processing', 'result': '{"ok":true,"elapsed":7.2}'}),
            AgentEvent(EventType.TOOL_USE, {'name': 'run_processing', 'input': {'alg_id': 'native:buffer'}}),
            AgentEvent(EventType.TOOL_RESULT, {'name': 'run_processing', 'result': '{"ok":true,"elapsed":2}'}),
        ]
        trace = [event_record(event, start) for event in events]
        self.assertEqual(smp_export_seconds(trace), 7.2)
        self.assertNotIn('result', trace[1]['data'])

    @classmethod
    def setUpClass(cls):
        cls.app = QgsApplication.instance() or QgsApplication([], True)
        cls.app.initQgis()

    def test_worker_dispatch_history_and_trace(self):
        main_thread = threading.get_ident()
        observed = []

        class Backend:
            def __init__(self, config, toolkit, executor):
                self.executor = executor
                self.toolkit = toolkit

            def send(self, message, history, emit, should_stop):
                observed.append((threading.get_ident(), list(history),
                                 self.executor.run_sync(threading.get_ident)))
                if not history:
                    self.toolkit.ask_user('Qual território?', ['Rio Claro', 'Igarapé'])
                emit(AgentEvent(EventType.TEXT, {'text': 'Olá'}))
                return history + [message]

        def fixture(case, run_dir, variant):
            project = QgsProject.instance()
            project.clear()
            project_path = run_dir / 'project.qgz'
            project.write(str(project_path))
            output = run_dir / 'output'
            output.mkdir()
            (output / 'sample.txt').write_text('synthetic')
            return SimpleNamespace(project_path=project_path, output_dir=output, turns=('um', 'dois'))

        with tempfile.TemporaryDirectory() as tmp:
            with patch(f'{EVAL_MODULE}.fixtures.build_fixture', side_effect=fixture), \
                    patch(f'{EVAL_MODULE}.checks.evaluate', return_value=[
                        {'id': 'example', 'status': 'manual', 'detail': 'review'}]):
                trace = run_case('load', Path(tmp) / 'run', 'offline', 'fake', backend_factory=Backend)
            self.assertEqual(trace['turns'][0]['reply'], 'Olá')
            self.assertEqual(trace['turns'][0]['questions'], ['Qual território?'])
            self.assertEqual(trace['metrics']['clarification_turns'], 1)
            reply_checks = [check for check in trace['checks'] if check['id'].startswith('visible_reply_')]
            self.assertEqual([(check['id'], check['status']) for check in reply_checks],
                             [('visible_reply_1', 'pass'), ('visible_reply_2', 'pass')])
            self.assertTrue(observed[1][1][0].startswith('um'))
            self.assertNotEqual(observed[0][0], main_thread)
            self.assertEqual(observed[0][2], main_thread)
            self.assertEqual(trace['artifacts'], ['sample.txt'])
            self.assertEqual(json.loads((Path(tmp) / 'run' / 'run.json').read_text())['status'], 'completed')

    def test_supervisor_timeout_writes_report(self):
        supervise = import_module(f"{EVAL_MODULE}.__main__").supervise

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'run'
            status = supervise([sys.executable, '-c', 'import time; time.sleep(30)'], output, 0.1,
                               {'case': 'load'})
            self.assertEqual(status, 'timeout')
            report = json.loads((output / 'run.json').read_text())
            self.assertEqual(report['status'], 'timeout')
            self.assertEqual(report['checks'][0]['status'], 'blocked')

    def test_real_fixture_and_missing_plugin_are_reported(self):
        class Backend:
            def __init__(self, config, toolkit, executor):
                pass

            def send(self, message, history, emit, should_stop):
                emit(AgentEvent(EventType.TEXT, {'text': 'teste'}))
                return history

        with tempfile.TemporaryDirectory() as tmp:
            trace = run_case('smp_region', Path(tmp) / 'run', 'offline', 'fake', backend_factory=Backend)
            self.assertEqual(trace['status'], 'blocked')
            self.assertIn('algorithm', trace['checks'][0]['detail'])

    def test_final_reply_is_checked_for_each_completed_turn(self):
        visible_reply_check = import_module(f'{EVAL_MODULE}.runner').visible_reply_check

        turn = {'events': [
            {'type': 'text', 'data': {'text': 'Vou verificar.'}},
            {'type': 'tool_use', 'data': {'name': 'list_layers'}},
            {'type': 'tool_result', 'data': {'name': 'list_layers'}},
        ], 'questions': []}
        self.assertEqual(visible_reply_check(turn, 0)['status'], 'fail')
        turn['events'].append({'type': 'text', 'data': {'text': 'Encontrei duas camadas.'}})
        self.assertEqual(visible_reply_check(turn, 1)['status'], 'pass')
        turn['events'] = [{'type': 'tool_use', 'data': {'name': 'ask_user'}},
                          {'type': 'user_question', 'data': {'question': 'Qual território?'}},
                          {'type': 'tool_result', 'data': {'name': 'ask_user'}}]
        turn['questions'] = ['Qual território?']
        dismissed = AgentEvent(EventType.TOOL_RESULT, {
            'name': 'ask_user', 'is_error': False, 'cancelled': True,
            'result': '{"choice": null, "free_text": null, "cancelled": true}',
        })
        turn['events'][-1] = event_record(dismissed, time.monotonic())
        self.assertEqual(turn['events'][-1]['data']['status'], 'dismissed')
        self.assertEqual(visible_reply_check(turn, 0)['status'], 'pass')
        turn['events'][-1]['data']['status'] = 'error'
        self.assertEqual(visible_reply_check(turn, 0)['status'], 'fail')
        turn['events'][-1]['data'].pop('status')
        turn['events'].extend([{'type': 'tool_use', 'data': {'name': 'ask_user'}},
                               {'type': 'tool_result', 'data': {'name': 'ask_user'}}])
        self.assertEqual(visible_reply_check(turn, 0)['status'], 'fail')
        turn['events'].append({'type': 'tool_result', 'data': {'name': 'list_layers'}})
        self.assertEqual(visible_reply_check(turn, 0)['status'], 'fail')
        turn['error'] = 'Timeout'
        self.assertEqual(visible_reply_check(turn, 0)['status'], 'blocked')

    def test_workflow_aggregate_includes_missing_final_reply(self):
        class Backend:
            def __init__(self, config, toolkit, executor):
                pass

            def send(self, message, history, emit, should_stop):
                emit(AgentEvent(EventType.TEXT, {'text': 'Vou verificar.'}))
                emit(AgentEvent(EventType.TOOL_USE, {'name': 'list_layers', 'input': {}}))
                emit(AgentEvent(EventType.TOOL_RESULT, {'name': 'list_layers', 'result': '{}'}))
                return history + [message]

        with tempfile.TemporaryDirectory() as tmp:
            with patch(f'{EVAL_MODULE}.checks.evaluate', return_value=[
                    {'id': 'workflow', 'status': 'pass', 'detail': 'Components passed.'}]), \
                    patch(f'{EVAL_MODULE}.checks.evaluate_step', return_value={
                        'id': 'stage', 'status': 'pass', 'detail': 'passed'}):
                trace = run_case('workflow', Path(tmp) / 'run', 'offline', 'fake', backend_factory=Backend)
            workflow = next(check for check in trace['checks'] if check['id'] == 'workflow')
            self.assertEqual(workflow['status'], 'fail')
            self.assertTrue(all(check['status'] == 'fail' for check in trace['checks']
                                if check['id'].startswith('visible_reply_')))

    def test_captures_first_native_pdf_before_layout_is_changed(self):
        from qgis.core import QgsLayoutItemMap, QgsPrintLayout

        class Backend:
            def __init__(self, config, toolkit, executor):
                self.toolkit = toolkit
                self.executor = executor

            def send(self, message, history, emit, should_stop):
                def export():
                    project = QgsProject.instance()
                    layout = QgsPrintLayout(project)
                    layout.initializeDefaults()
                    layout.setName('Mapa')
                    project.layoutManager().addLayout(layout)
                    path = self.toolkit.input_dir.parent / 'outputs' / 'mapa.pdf'
                    first = self.toolkit.export_layout('Mapa', str(path))
                    if not first['ok']:
                        raise RuntimeError(first['error'])
                    layout.addLayoutItem(QgsLayoutItemMap(layout))

                self.executor.run_sync(export)
                emit(AgentEvent(EventType.TEXT, {'text': 'PDF criado.'}))
                return history + [message]

        with tempfile.TemporaryDirectory() as tmp:
            trace = run_case('pdf_basemap', Path(tmp) / 'run', 'offline', 'fake', backend_factory=Backend)
            self.assertEqual(trace['first_pdf_export']['output'], 'mapa.pdf')
            self.assertEqual(trace['first_pdf_export']['map_layer_ids'], [])
            self.assertEqual(len(trace['first_pdf_export']['sha256']), 64)

    def test_selection_is_seeded_in_active_layer_after_project_load(self):
        class Backend:
            def __init__(self, config, toolkit, executor):
                self.toolkit = toolkit
                self.executor = executor

            def send(self, message, history, emit, should_stop):
                def selected_names():
                    layer = self.toolkit.iface.activeLayer()
                    return [str(feature['nome']) for feature in layer.selectedFeatures()]

                names = self.executor.run_sync(selected_names)
                emit(AgentEvent(EventType.TEXT, {'text': ', '.join(names)}))
                return history + [message]

        with tempfile.TemporaryDirectory() as tmp:
            trace = run_case('selection', Path(tmp) / 'run', 'offline', 'fake', backend_factory=Backend)
            self.assertEqual(trace['status'], 'completed')
            self.assertEqual(trace['checks'][0]['status'], 'pass', trace['checks'][0])

    def test_selection_is_seeded_when_heldout_fixture_renames_the_layer(self):
        class Backend:
            def __init__(self, config, toolkit, executor):
                self.toolkit = toolkit
                self.executor = executor

            def send(self, message, history, emit, should_stop):
                def selected_names():
                    layer = self.toolkit.iface.activeLayer()
                    return [str(feature['nome']) for feature in layer.selectedFeatures()]

                emit(AgentEvent(EventType.TEXT, {'text': ', '.join(self.executor.run_sync(selected_names))}))
                return history + [message]

        with tempfile.TemporaryDirectory() as tmp:
            trace = run_case('selection', Path(tmp) / 'run', 'offline', 'fake', 'heldout', backend_factory=Backend)
            self.assertEqual(trace['status'], 'completed')
            self.assertEqual(trace['turns'][0]['reply'], 'Aldeia Arumã (teste), Aldeia Samaúma (teste)')
            self.assertEqual(trace['checks'][0]['status'], 'pass', trace['checks'][0])

    def test_unattended_run_approves_its_own_files_and_gates_everything_else(self):
        runner = import_module(f"{EVAL_MODULE}.runner")

        def gated(run_dir, tool, **arguments):
            toolkit = runner.EvalToolkit(None, runner.EvalConfig('offline', 'fake'), run_dir / 'inputs')
            return toolkit.confirm_external_access(tool, arguments) is not None

        with tempfile.TemporaryDirectory() as tmp:
            self.run_dir = Path(tmp).resolve()
            inputs, outputs = self.run_dir / 'inputs', self.run_dir / 'outputs'
            inputs.mkdir()
            outputs.mkdir()
            (inputs / 'dados_aldeias.csv').write_text('codigo,pop\nA1,120\n', encoding='utf-8')
            table, saved = inputs / 'dados_aldeias.csv', outputs / 'escola_sim.geojson'

            approved = (
                ('add_layer', {'uri': str(table), 'provider': 'ogr'}),
                ('add_layer', {'uri': str(table) + '?type=csv', 'provider': 'ogr'}),
                ('add_layer', {'uri': str(table) + '|geomType=none', 'provider': 'ogr'}),
                ('add_layer', {'uri': f'file://{table}?type=csv&geomType=none', 'provider': 'delimitedtext'}),
                ('add_layer', {'uri': str(table), 'provider': 'delimitedtext'}),
                ('add_layer', {'uri': str(saved), 'provider': 'ogr'}),
                ('run_processing', {'alg_id': 'native:extractbyattribute',
                                    'params': {'INPUT': 'Aldeias', 'OUTPUT': str(saved)}}),
                ('run_processing', {'alg_id': 'native:extractbyattribute',
                                    'params': {'INPUT': 'Aldeias', 'OUTPUT': 'memory:'}}),
                ('run_processing', {'alg_id': 'smp:generatesmp',
                                    'params': {'EXTENT': '-60.85,-2.85,-60.20,-2.15 [EPSG:4326]',
                                               'OUTPUT_FILE': str(outputs / 'territorio.smp')}}),
                ('run_pyqgis', {'code': f"open('{saved}', 'w').write('ok')"}),
                ('run_pyqgis', {'code': f"open('{table}').read()"}),
                ('run_pyqgis', {'code': "Path(output_dir) / 'escola.geojson'"}),
                ('run_pyqgis', {'code': "result = [f['nome'] for f in _sample_features(get_layer('Aldeias'))]"}),
            )
            for tool, arguments in approved:
                self.assertFalse(gated(self.run_dir, tool, **arguments), (tool, arguments))

            blocked = (
                ('add_layer', {'uri': 'type=xyz&url=https://mt1.google.com/vt/lyrs=s&z={z}&y={y}&x={x}'}),
                ('add_layer', {'uri': 'https://example.org/fundo.tif', 'provider': 'gdal'}),
                ('add_layer', {'uri': '/etc/hosts', 'provider': 'ogr'}),
                ('add_layer', {'uri': 'file:///etc/hosts', 'provider': 'delimitedtext'}),
                ('add_layer', {'uri': str(Path(tmp).resolve().parent / 'outside.geojson'), 'provider': 'ogr'}),
                ('run_processing', {'alg_id': 'native:buffer',
                                    'params': {'INPUT': 'Aldeias', 'OUTPUT': '/tmp/fora.gpkg'}}),
                ('run_processing', {'alg_id': 'native:filedownloader',
                                    'params': {'URL': 'https://example.org/dados.zip'}}),
                ('run_pyqgis', {'code': "import urllib.request; result = urllib.request.urlopen('https://example.org')"}),
                ('run_pyqgis', {'code': "import os; result = os.environ['HOME']"}),
                ('run_pyqgis', {'code': "result = open('/etc/passwd').read()"}),
                ('run_pyqgis', {'code': "result = open('../fora.csv').read()"}),
                ('run_pyqgis', {'code': f"result = '{Path(tmp).resolve().parent}/fora.geojson'"}),
                ('web_fetch', {'url': 'https://example.org'}),
            )
            for tool, arguments in blocked:
                self.assertTrue(gated(self.run_dir, tool, **arguments), (tool, arguments))

    def test_supervisor_reports_the_worker_exit_code(self):
        supervise = import_module(f"{EVAL_MODULE}.__main__").supervise
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'run'
            status = supervise([sys.executable, '-c', 'import sys; sys.exit(3)'], output, 30, {'case': 'load'})
            self.assertEqual(status, 'error')
            report = json.loads((output / 'run.json').read_text())
            self.assertEqual(report['status'], 'error')
            self.assertIn('exited with code 3', report['checks'][0]['detail'])
