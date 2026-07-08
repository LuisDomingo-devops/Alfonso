import pytest
from app.domain.intent_router import IntentRouter


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


def test_intent_router_accents_optional():
    router = IntentRouter()
    
    # "dame la informacion del sistema" (sin tilde) debe matchear sysinfo y tener intent="tool"
    res1 = router.detect_with_detail("dame la informacion del sistema")
    assert res1["intent"] == "tool"
    assert any("sysinfo" in r for r in res1["fired_rules"])
    
    # "que hora es" (sin tilde en qué)
    res2 = router.detect_with_detail("que hora es")
    assert res2["intent"] == "tool"
    assert any("datetime_tool" in r for r in res2["fired_rules"])

    # "que contiene mi escritorio" y "lista mi desktop"
    res3 = router.detect_with_detail("que contiene mi escritorio")
    assert res3["intent"] == "tool"
    assert any("fs_list" in r for r in res3["fired_rules"])

    res4 = router.detect_with_detail("lista mi desktop")
    assert res4["intent"] == "tool"
    assert any("fs_list" in r for r in res4["fired_rules"])


def test_intent_router_mail():
    router = IntentRouter()
    
    # Generar correos
    res1 = router.detect_with_detail("Genera correos de prueba")
    assert res1["intent"] == "tool"
    assert any("mail_seed" in r for r in res1["fired_rules"])
    
    # Resumen
    res2 = router.detect_with_detail("Dame el resumen de correo de esta mañana")
    assert res2["intent"] == "tool"
    assert any("mail_summary" in r for r in res2["fired_rules"])


