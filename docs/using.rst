Using FabulAWS in your fab file
===============================

FabulAWS uses `Fabric <http://www.fabfile.org/>`_ internally to communicate
with newly-created servers, so it follows naturally that you can use FabulAWS
in your fab files to create new servers and deploy code to them.

Simple Fabric example
---------------------

Adding ``fabulaws`` to an existing fab file can be as simple as importing
and instantiating an EC2 instance class, e.g.::

    from fabric.api import *
    from fabulaws.ec2 import MicroUbuntuInstance

    def new_instance():
        i = MicroUbuntuInstance()
        env.hosts = [i.hostname]

    def bootstrap():
        run('git clone %s' % env.repo)

The ``new_instance`` method creates a new Amazon EC2 instance and gives you
access to the hostname of that newly created instance, so running::

    fab new_instance bootstrap
    Connecting to EC2...

would create a new copy of that instance on Amazon, using the API key in
your shell environment.


Tagging instances
-----------------

To make it easier to keep track of your instances on EC2, you can tag them
with your environment (e.g., ``'staging'`` or ``'production'``), as well as
something that identifies the product or group of servers that you're
deploying::

    from fabric.api import *
    from fabulaws.ec2 import MicroUbuntuInstance

    def new_instance(environment):
        tags = {'environment': environment, 'product': 'caktus-website'}
        i = MicroUbuntuInstance(tags=tags)
        env.hosts = [i.hostname]

    def bootstrap():
        run('git clone %s' % env.repo)

Now, you can pass the environment that you're creating into when you run
``fab``::

    fab new_instance:staging bootstrap
    Connecting to EC2...


Retrieving tagged instances
---------------------------

To retrieve and use tagged instances from your fab file, use the ``ec2_hostnames``
method in ``fabulaws.api`` to retrieve the hostnames for the instances
tagged with the appropriate tags, e.g.::

    from fabric.api import *
    from fabulaws.api import *

    def staging():
        filters = {'tag:environment': 'staging', 'tag:product': 'caktus-website'}
        env.hosts = ec2_hostnames(filters=filters)

    def update():
        run('git pull')

Then, you can run ``fab`` as you normally would from the command line, and
it will reach out to EC2 to retrieve the hostname(s) for your server(s)
before running commands on them::

    $ fab staging deploy
    Connecting to EC2...

