def test_internet_status():
    """Test that internet status is correctly detected as DISCONNECTED"""
    with open("/app/internet_status.txt") as f:
        status = f.read().strip()

    assert status == "DISCONNECTED", f"Expected 'DISCONNECTED' but got '{status}'"
