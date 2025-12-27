import json
import os


def test_network_results_exist():
    """Test that network_test.json file exists"""
    assert os.path.exists("/app/network_test.json"), "network_test.json should exist"


def test_internal_network_connected():
    """Test that internal network between containers works"""
    with open("/app/network_test.json") as f:
        data = json.load(f)

    assert "internal_network" in data, "Result should contain 'internal_network' key"
    assert data["internal_network"] == "CONNECTED", f"Internal network should be CONNECTED but got '{data['internal_network']}'"


def test_internet_disconnected():
    """Test that internet is blocked"""
    with open("/app/network_test.json") as f:
        data = json.load(f)

    assert "internet" in data, "Result should contain 'internet' key"
    assert data["internet"] == "DISCONNECTED", f"Internet should be DISCONNECTED but got '{data['internet']}'"
