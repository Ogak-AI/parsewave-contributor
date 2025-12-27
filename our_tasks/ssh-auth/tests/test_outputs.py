import os

import paramiko

SERVER = "server"
USER = "llm"
PASSWORD = "37"


def ssh_connect_with_key():
    key = paramiko.RSAKey.from_private_key_file(f"/home/{USER}/.ssh/id_rsa")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(SERVER, username=USER, pkey=key)
    return client


def test_keypair_exists():
    """Verify that SSH key pair files exist on the client machine."""
    assert os.path.exists(f"/home/{USER}/.ssh/id_rsa")
    assert os.path.exists(f"/home/{USER}/.ssh/id_rsa.pub")


def test_authorized_keys_exists():
    """Verify that the authorized_keys file exists on the server."""
    client = ssh_connect_with_key()
    _, stdout, _ = client.exec_command(
        f"test -f /home/{USER}/.ssh/authorized_keys && echo 'exists'"
    )
    result = stdout.read().decode().strip()
    client.close()
    assert result == "exists"


def test_permissions():
    """Verify that SSH directory and authorized_keys file have correct permissions (700 and 600 respectively)."""
    client = ssh_connect_with_key()
    _, stdout, _ = client.exec_command(f"stat -c '%a' /home/{USER}/.ssh")
    dir_perms = stdout.read().decode().strip()
    _, stdout, _ = client.exec_command(
        f"stat -c '%a' /home/{USER}/.ssh/authorized_keys"
    )
    file_perms = stdout.read().decode().strip()
    client.close()
    assert dir_perms == "700", f".ssh dir must be 700, got {dir_perms}"
    assert file_perms == "600", f"authorized_keys must be 600, got {file_perms}"


def test_sshd_config_pubkey_enabled():
    """Verify that SSH server configuration enables public key authentication."""
    client = ssh_connect_with_key()
    _, stdout, _ = client.exec_command(
        "grep 'PubkeyAuthentication yes' /etc/ssh/sshd_config"
    )
    result = stdout.read().decode().strip()
    client.close()
    assert "PubkeyAuthentication yes" in result


def test_password_authentication_fails():
    """Verify that password authentication is disabled by attempting to connect with password."""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    # Attempt to connect using password authentication - this should fail
    try:
        client.connect(SERVER, username=USER, password=PASSWORD, look_for_keys=False, allow_agent=False)
        client.close()
        # If we reach here, password auth succeeded when it shouldn't have
        assert False, "Password authentication should be disabled but connection succeeded"
    except paramiko.ssh_exception.AuthenticationException:
        # This is expected - password authentication should fail
        pass
    except Exception as e:
        # Any other exception is unexpected
        assert False, f"Unexpected exception during password auth attempt: {e}"


def test_login_without_password():
    """Verify that SSH connection works using key-based authentication without password."""
    client = ssh_connect_with_key()
    _, stdout, _ = client.exec_command("whoami")
    assert stdout.read().decode().strip() == USER
    client.close()
