import xml.etree.ElementTree as ET

from prestige.eval import figures


def test_attack_figure_is_valid_svg_in_both_themes():
    for theme in figures.THEMES.values():
        svg = figures.fig_attacks(theme)
        root = ET.fromstring(svg)  # parses, so it's well-formed
        assert root.tag.endswith("svg")
        assert "Prestige: 0 of 70" in svg and "No gateway: 42 of 70" in svg


def test_text_is_escaped():
    svg = figures.Svg(10, figures.THEMES["light"], "a < b & c")
    svg.text(0, 0, "<script>")
    assert "<script>" not in svg.done()
