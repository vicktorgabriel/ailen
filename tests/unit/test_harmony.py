from __future__ import annotations

import json

import pytest

from ailen.ai.http_backend import GenericOpenAiBackend


def _strip_harmony(text: str) -> str:
    from ailen.ai.harmony import strip_harmony_channels

    return strip_harmony_channels(text)


def test_text_without_harmony_channel_marker_is_unchanged() -> None:
    text = '  respuesta normal {"final":"ok"}  '

    assert _strip_harmony(text) == text


def test_analysis_y_final_devuelve_solo_el_canal_final() -> None:
    text = (
        "<|start|>assistant<|channel|>analysis<|message|>razonamiento privado"
        "<|end|><|start|>assistant<|channel|>final <|constrain|>JSON"
        '<|message|>{"final":"hola"}<|return|>'
    )

    assert _strip_harmony(text) == '{"final":"hola"}'


def test_solo_analysis_no_expone_razonamiento() -> None:
    assert _strip_harmony(
        "<|channel|>analysis<|message|>no debe salir<|end|>"
    ) == ""


def test_elige_el_ultimo_canal_final_entre_varios_canales() -> None:
    text = (
        "<|channel|>analysis<|message|>privado<|end|>"
        "<|channel|>commentary<|message|>interno<|end|>"
        "<|channel|>final<|message|>primero<|end|>"
        "<|channel|>analysis<|message|>más privado<|end|>"
        "<|channel|>final<|constrain|>json<|message|>último<|end|>"
    )

    assert _strip_harmony(text) == "último"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("<|channel|>final <|constrain|>JSON", ""),
        ("<|channel|>final<|message|>respuesta sin cierre", "respuesta sin cierre"),
        ("<|channel|>final<|message|>incompleto<|end", "incompleto<|end"),
    ],
)
def test_marcador_truncado_no_filtra_header_y_conserva_final_disponible(
    text: str, expected: str
) -> None:
    assert _strip_harmony(text) == expected


def test_json_dentro_de_final_se_conserva_exactamente() -> None:
    payload = '{"tool":"clock","arguments":{"format":"time"}}'
    text = f"<|channel|>final <|constrain|>JSON<|message|>{payload}<|end|>"

    assert json.loads(_strip_harmony(text)) == json.loads(payload)


def test_incremental_filter_handles_markers_split_across_chunks() -> None:
    from ailen.ai.harmony import HarmonyStreamFilter

    parser = HarmonyStreamFilter()
    chunks = [
        "<|chan", "nel|>analysis<|mes", "sage|>private reasoning<|end|>",
        "<|channel|>commentary<|message|>internal note<|end|>",
        "<|channel|>final <|constrain|>JSON<|message|>{\"final\":",
        "\"visible\"}<|return|>",
    ]
    emitted = "".join(parser.feed(chunk) for chunk in chunks) + parser.finish()

    assert emitted == '{"final":"visible"}'
    assert "private" not in emitted
    assert "internal" not in emitted


def test_openai_compatible_non_stream_response_quita_canales_harmony() -> None:
    backend = GenericOpenAiBackend(endpoint="http://127.0.0.1:8080/v1", model="local")
    content = (
        "<|channel|>analysis<|message|>razonamiento que no debe salir<|end|>"
        '<|channel|>final <|constrain|>JSON<|message|>{"final":"hola"}<|end|>'
    )
    raw_body = json.dumps({"model": "local", "choices": [{"message": {"content": content}}]})

    response = backend._parse_success_response(raw_body, 1.0, request_chars=10)

    assert response.text == '{"final":"hola"}'
