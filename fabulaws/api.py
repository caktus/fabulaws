import json
import tempfile

from fabric.api import *
from fabric.operations import _prefix_commands, _prefix_env_vars


__all__ = ['sshagent_run', 'call_python', 'ec2_hostnames', 'ec2_instances', 'answer_sudo']


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
    opts = ['-A']
    if env.disable_known_hosts:
        opts += ['-o StrictHostKeyChecking=no',
                 '-o UserKnownHostsFile=/dev/null']
    try:
        host, port = env.host_string.split(':')
        opts.append('-p %s' % port)
    except ValueError:
        host = env.host_string
    opts = ' '.join(opts)
    return local("ssh %s %s@%s '%s'" % (opts, user, host, wrapped_cmd))


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


def answer_sudo(cmd, *args, **kwargs):
    """
    Answers questions presented via standard out according to the
    given answers.  The ``answers`` keyword argument should be a list of
    (question, answer) pairs.  The questions are in regular expression format,
    so ensure that any special characters are appropriately escaped.
    """
    answers = kwargs.pop('answers', [])
    if answers:
        # use shared memory rather than potentially writing passwords to the
        # most likely unencrypted disk
        script = tempfile.NamedTemporaryFile(dir='/dev/shm')
        script.writelines([
            "import pexpect, sys\n",
            "child = pexpect.spawn('{0}')\n".format(cmd),
            "child.logfile = sys.stdout\n"
        ])
        for question, answer in answers:
            script.writelines([
                "child.expect('{0}')\n".format(question),
                "child.sendline('{0}')\n".format(answer),
            ])
        # this is important, otherwise pexect will kill the process before it's
        # finished
        script.writelines(["child.wait()\n"])
        script.flush()
        put(script.name, script.name, mirror_local_mode=True)
        cmd = 'python {0}'.format(script.name)
    result = sudo(cmd, *args, **kwargs)
    if answers:
        run('rm {0}'.format(script.name))
    return result
