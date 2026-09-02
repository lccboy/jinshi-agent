from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_server_api_runtime_uses_certifi_for_https_collectors():
    script = (ROOT / "deploy" / "run-server-api.cmd").read_text(encoding="utf-8")
    assert "import certifi; print(certifi.where())" in script
    assert "set SSL_CERT_FILE=" in script
    assert script.index("set SSL_CERT_FILE=") < script.index("services\\market_data_service.py")
