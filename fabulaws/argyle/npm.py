from fabric.api import sudo, task


@task
def npm_command(command):
    """Run a NPM command."""

    sudo(u'npm %s' % command)


@task
def npm_install(package, flags=None):
    """Install a package from NPM."""

    command = u'install %s %s' % (package, flags or u'') 
    npm_command(command.strip())


@task
def npm_uninstall(package):
    """Uninstall a package from NPM."""

    command = u'uninstall %s' % package
    npm_command(command)


@task
def npm_update(package):
    """Update a package from NPM."""

    command = u'update %s' % package
    npm_command(command)
