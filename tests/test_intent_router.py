import pytest
from app.core.intent_router import IntentRouter


def test_intent_router_chat():
    router = IntentRouter()
    
    # Mensajes tipo chat
    res1 = router.detect_with_detail("hola Alfonso, ¿cómo estás?")
    assert res1["intent"] == "chat"
    
    res2 = router.detect_with_detail("explícame qué es la fotosíntesis")
    assert res2["intent"] == "chat"


def test_intent_router_datetime():
    router = IntentRouter()
    
    # Mensajes sobre fecha/hora
    res1 = router.detect_with_detail("¿qué hora es?")
    assert res1["intent"] == "tool"
    assert any("datetime_tool" in r for r in res1["fired_rules"])
    
    res2 = router.detect_with_detail("dime la fecha de hoy por favor")
    assert res2["intent"] == "tool"
    assert any("datetime_tool" in r for r in res2["fired_rules"])


def test_intent_router_filesystem():
    router = IntentRouter()
    
    # Crear archivo
    res1 = router.detect_with_detail("crea un archivo de texto llamado notas.txt")
    assert res1["intent"] == "tool"
    
    # Eliminar
    res2 = router.detect_with_detail("borra el archivo temporal")
    assert res2["intent"] == "tool"


def test_intent_router_browser():
    router = IntentRouter()
    
    # Navegación y búsqueda
    res1 = router.detect_with_detail("navega a https://google.com")
    assert res1["intent"] == "tool"
    
    res2 = router.detect_with_detail("busca en internet noticias sobre el clima")
    assert res2["intent"] == "tool"
