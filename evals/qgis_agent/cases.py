"""Deterministic case definitions for the AwanaGIS QGIS agent evaluation."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Case:
    case_id: str
    turns: tuple[str, ...]
    expected_layers: tuple[str, ...] = ()
    assistant_checkpoints: tuple[str, ...] = ()


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
}
