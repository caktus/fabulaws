import re

from fabric.api import put, sudo, task, env, hide, settings, run
from fabric.contrib import files


def _read_lines_from_file(file_name):
    with open(file_name) as f:
        packages = f.readlines()
    return map(lambda x: x.strip('\n\r'), packages)


def user_exists(username):
    exists = False
    with settings(hide('everything'), warn_only=True):
        exists = run(u"grep ^%s /etc/passwd" % username)
    return exists


def group_exists(name):
    exists = False
    with settings(hide('everything'), warn_only=True):
        exists = run(u"grep ^%s /etc/group" % name)
    return exists


@task
def install_packages(*packages):
    """Install apt packages from a list."""

    sudo(u"apt-get install -y %s" % u" ".join(packages))


@task
def install_packages_from_file(file_name):
    """Install apt packages from a file list."""

    install_packages(*_read_lines_from_file(file_name))


@task
def update_apt_sources():
    """Update apt source."""

    sudo(u"apt-get update")


@task
def upgrade_apt_packages():
    """Safe upgrade of all packages."""

    update_apt_sources()
    sudo(u"apt-get upgrade -y")


@task
def add_ppa(name, update=True):
    """Add personal package archive."""

    sudo(u"add-apt-repository %s" % name)
    if update:
        update_apt_sources()


@task
def add_ppas_from_file(file_name, update=True):
    """Add personal package archive from a file list."""

    for ppa in _read_lines_from_file(file_name):
        add_ppa(ppa, update=False)
    if update:
        update_apt_sources()


@task
def add_apt_source(source, key=None, update=True):
    """Adds source url to apt sources.list. Optional to pass the key url."""

    # Make a backup of list
    source_list = u'/etc/apt/sources.list'
    sudo("cp %s{,.bak}" % source_list)
    files.append(source_list, source, use_sudo=True)
    if key:
        # Fecth key from url and add
        sudo(u"wget -q %s -O - | sudo apt-key add -" % key)
    if update:
        update_apt_sources()


@task
def add_sources_from_file(file_name, update=True):
    """
    Add source urls from a file list.
    The file should contain the source line to add followed by the
    key url, if any, enclosed in parentheses.

    Ex:
    deb http://example.com/deb lucid main (http://example.com/key)
    """

    key_regex = re.compile(r'(?P<source>[^()]*)(\s+\((?P<key>.*)\))?$')
    for line in _read_lines_from_file(file_name):
        kwargs = key_regex.match(line).groupdict()
        kwargs['update'] = False
        add_apt_source(**kwargs)
    if update:
        update_apt_sources()


@task
def create_user(name, groups=None, key_file=None):
    """Create a user. Adds a key file to authorized_keys if given."""

    groups = groups or []
    if not user_exists(name):
        for group in groups:
            if not group_exists(group):
                sudo(u"addgroup %s" % group)
        groups = groups and u'-G %s' % u','.join(groups) or ''
        sudo(u"useradd -m %s -s /bin/bash %s" % (groups, name))
        sudo(u"passwd -d %s" % name)
    if key_file:
        sudo(u"mkdir -p /home/%s/.ssh" % name)
        put(key_file, u"/home/%s/.ssh/authorized_keys" % name, use_sudo=True)
        sudo(u"chown -R %(name)s:%(name)s /home/%(name)s/.ssh" % {'name': name})


@task
def service_command(name, command):
    """Run an init.d/upstart command."""

    service_command_template = getattr(env, 'ARGYLE_SERVICE_COMMAND_TEMPLATE',
                                       u'/etc/init.d/%(name)s %(command)s')
    sudo(service_command_template % {'name': name,
                                     'command': command}, pty=False)


@task
def start_service(name):
    """Start an init.d service."""

    service_command(name, u"start")


@task
def stop_service(name):
    """Stop an init.d service."""

    service_command(name, u"stop")


@task
def restart_service(name):
    """Restart an init.d service."""

    service_command(name, u"restart")
