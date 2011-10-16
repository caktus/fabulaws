import json

from fabric.api import *
from fabric.operations import _prefix_commands, _prefix_env_vars


__all__ = ['sshagent_run', 'call_python', 'ec2_hostnames', 'ec2_instances']


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


def call_python(method, *args):
    """
    Call the given ``method'' with the given ``args'' in Python on the
    remote server.  ``method'' should be the full Python path to the
    method.  Only JSON-serializable arguments and return values are
    supported.
    """
    module = '.'.join(method.split('.')[:-1])
    args = json.dumps(args)[1:-1]
    output = run('/usr/bin/env python -c \'import json, {module};'
                 'print json.dumps({method}({args}))\''
                 ''.format(module=module, method=method, args=args))
    return json.loads(output)


def ec2_hostnames(*args, **kwargs):
    """
    Returns a list of hostnames for the specified filters.
    """
    from fabulaws.ec2 import EC2Service
    return EC2Service().public_dns(*args, **kwargs)


def ec2_instances(*args, **kwargs):
    """
    Returns a list of instances for the specified filters.
    """
    from fabulaws.ec2 import EC2Service
    return EC2Service().instances(*args, **kwargs)
