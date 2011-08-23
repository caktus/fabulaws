from fabric.api import *
from fabric.operations import _prefix_commands, _prefix_env_vars

__all__ = ['sshagent_run']


def sshagent_run(cmd, user=None):
    """
    Helper function.
    Runs a command with SSH agent forwarding enabled.

    Note:: Fabric (and paramiko) can't forward your SSH agent.
    This helper uses your system's ssh to do so.
    """
    # Handle context manager modifications
    wrapped_cmd = _prefix_commands(_prefix_env_vars(cmd), 'remote')
    if user is None:
        user = env.user
    try:
        host, port = env.host_string.split(':')
        return local("ssh -o StrictHostKeyChecking=no -p "
                     "%s -A %s@%s '%s'" % (port, user, host, wrapped_cmd))
    except ValueError:
        return local("ssh -o StrictHostKeyChecking=no -A "
                     "%s@%s '%s'" % (user, env.host_string, wrapped_cmd))
