"""Deterministic case definitions for the AwanaGIS QGIS agent evaluation."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Case:
    case_id: str
    turns: tuple[str, ...]
    expected_layers: tuple[str, ...] = ()
    assistant_checkpoints: tuple[str, ...] = ()
    # Prompts for the held-out fixture, when it names other layers or files.
    heldout_turns: tuple[str, ...] = ()


CASES = {
    "basemap": Case(
        "basemap",
        ("Coloca um mapa de fundo.",),
        ("Google Satellite",),
    ),
    "load": Case(
        "load",
        ("Abre esses arquivos e me explica o que tem neles.",),
        ("Aldeias", "Territórios", "Dados das aldeias"),
    ),
    "style": Case(
        "style",
        ("Deixa as aldeias em azul, troca o símbolo e mostra os nomes.",),
        ("Aldeias",),
    ),
    "crs_view": Case(
        "crs_view",
        ("Ajuste a visualização para mostrar todo o território e as aldeias juntas.",),
        ("Aldeias", "Territórios", "Fundo sintético"),
    ),
    "pdf_basemap": Case(
        "pdf_basemap",
        ("Faz um PDF do mapa atual, incluindo o fundo raster local.",),
        ("Fundo sintético",),
    ),
    "selection": Case(
        "selection",
        ("Quais aldeias já estão selecionadas no mapa?",),
        ("Aldeias",),
    ),
    "category_split": Case(
        "category_split",
        ("Separe as aldeias em duas camadas, com escola e sem escola. Coloque um ícone diferente em cada camada.",),
        ("Aldeias",),
    ),
    "dedup": Case(
        "dedup",
        ("Crie uma camada sem as duplicatas. Use o código da aldeia para manter uma só de cada.",),
        ("Aldeias duplicadas",),
    ),
    "filter_join": Case(
        "filter_join",
        ("Mostra só as aldeias com escola e junta com essa tabela.",),
        ("Aldeias", "Dados das aldeias"),
    ),
    "pdf": Case("pdf", ("Faz um PDF desse mapa pra reunião.",)),
    "smp_territory": Case(
        "smp_territory",
        ("Cria um mapa para o Mapeo.", "Quero só o território inteiro, sem uma área com mais detalhe."),
        ("Territórios",),
    ),
    "smp_region": Case(
        "smp_region",
        (
            "Cria um mapa para o Mapeo.",
            "Pronto.",
        ),
        ("Territórios", "Aldeias"),
        ("Aproxime e mova o mapa até aparecer na tela toda a área que você quer ver com mais detalhes.",),
    ),
    "smp_ambiguous": Case(
        "smp_ambiguous",
        ("Cria um mapa para o Mapeo.",),
        ("Territórios",),
    ),
    "workflow": Case(
        "workflow",
        (
            "Coloca um mapa de fundo.",
            "Abre esses arquivos e me explica o que tem neles.",
            "Deixa as aldeias em azul, troca o símbolo e mostra os nomes.",
            "Mostra só as aldeias com escola e junta com essa tabela.",
            "Faz um PDF desse mapa pra reunião.",
            "Cria um mapa para o Mapeo.",
            "Quero só o território inteiro, sem uma área com mais detalhe.",
        ),
        ("Aldeias", "Territórios", "Dados das aldeias"),
    ),
    # The two cases below keep the shape of prompts people sent in a real
    # session: a derived layer the user wants kept on disk, a rule the user
    # states and then corrects, and a removal by the name of an area.
    "camps_merge": Case(
        "camps_merge",
        (
            "Analisa as camadas Pontos de campo e Observações e me diz quantos acampamentos há em cada uma "
            "e como você sugere classificar o tipo. Não salve nada ainda.",
            "Pode aplicar assim: junta os acampamentos das duas numa camada nova, sem alterar as originais. "
            "O tipo é vigilância quando o registro for de acampamento de vigilância, e não informado nos "
            "outros casos, por enquanto. Salve a camada como geojson, com o nome acampamentos.geojson, "
            "no mesmo local dos outros arquivos. Não é uma camada temporária.",
            "Tira da camada nova os pontos que estão dentro da Terra Indígena Rio Claro.",
            "Só a TI Rio Claro. E os pontos que sobraram que vieram de Pontos de campo passam a ser "
            "do tipo demarcação.",
        ),
        heldout_turns=(
            "Olha as camadas Registros de campo (teste) e Observações (teste) e me diz quantos acampamentos "
            "há em cada uma e como você sugere classificar o tipo. Não salve nada ainda.",
            "Aplica desta forma: reúne os acampamentos das duas numa camada nova, sem alterar as originais. "
            "O tipo é vigilância quando a categoria ou a nota falar em vigilância, e não informado nos "
            "outros casos, por enquanto. Salva a camada como geojson, com o nome base_campo.geojson, "
            "na mesma pasta dos outros arquivos. Não é uma camada temporária.",
            "Remove da camada nova os pontos dentro da Terra Indígena Uraricoera.",
            "Somente a TI Uraricoera. E os pontos que restaram que vieram de Observações (teste) passam a ser "
            "do tipo demarcação.",
        ),
    ),
    "layer_keep": Case(
        "layer_keep",
        (
            "Salva em um geojson só as aldeias com escola. Coloque o arquivo junto dos outros, com o nome "
            "aldeias_com_escola.geojson, e adicione como camada no projeto. Esse arquivo fica guardado, "
            "não é temporário.",
            "Tira essa camada do projeto, mas não apaga o arquivo.",
            "A camada aldeias_com_escola ainda está no projeto? Quantos pontos tem o arquivo?",
        ),
    ),
}
