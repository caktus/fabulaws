import os
from io import StringIO

from fabric.api import env, hide, local, put, run, settings, sudo
from fabric.contrib import files
from fabric.operations import _prefix_commands, _prefix_env_vars
from jinja2 import ChoiceLoader, Environment, FileSystemLoader, PackageLoader


def sshagent_run(cmd):
    """
    Helper function.
    Runs a command with SSH agent forwarding enabled.

    Note:: Fabric (and paramiko) can't forward your SSH agent.
    This helper uses your system's ssh to do so.
    """
    # Handle context manager modifications
    wrapped_cmd = _prefix_commands(_prefix_env_vars(cmd), 'remote')
    try:
        host, port = env.host_string.split(':')
        return local(
            u"ssh -p %s -A -o StrictHostKeyChecking=no %s@%s '%s'" % (
                port, env.user, host, wrapped_cmd
            )
        )
    except ValueError:
        return local(
            u"ssh -A -o StrictHostKeyChecking=no %s@%s '%s'" % (
                env.user, env.host_string, wrapped_cmd
            )
        )


def upload_template(filename, destination, context=None,
    use_sudo=False, backup=True, mode=None):
    func = use_sudo and sudo or run
    # Process template
    loaders = []
    template_dirs = getattr(env, 'ARGYLE_TEMPLATE_DIRS', ())
    if template_dirs:
        loaders.append(FileSystemLoader(template_dirs))
    loaders.append(PackageLoader('argyle'))
    jenv = Environment(loader=ChoiceLoader(loaders))
    context = context or {}
    env_context = env.copy()
    env_context.update(context)
    template = jenv.get_or_select_template(filename)
    text = template.render(env_context)
    # Normalize destination to be an actual filename, due to using StringIO
    with settings(hide('everything'), warn_only=True):
        if func('test -d %s' % destination).succeeded:
            sep = "" if destination.endswith('/') else "/"
            if hasattr(filename, '__iter__'):
                # Use selected filename for destination
                final = template.filename
            else:
                final = filename
            destination += sep + os.path.basename(final)
    # Back up original file
    if backup and files.exists(destination):
        func("cp %s{,.bak}" % destination)
    # Upload the file.
    put(
        local_path=StringIO(text),
        remote_path=destination,
        use_sudo=use_sudo,
        mode=mode
    )
