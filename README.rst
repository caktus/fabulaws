FabulAWS
========

`FabulAWS <https://github.com/caktus/fabulaws>`_ began as a tool to create
ephemeral EC2 instances using Python, like so::

    from fabulaws.ec2 import MicroLucidInstance

    with MicroLucidInstance():
        run('uname -a')

FabulAWS is now a fully-featured tool for deploying Python web applications
to autoscaling-enabled AWS EC2 environments.

Please refer to the `documentation <http://fabulaws.readthedocs.org/>`_ for
details.

Pre-commit
----------

This repo uses `pre-commit <https://pre-commit.com/>`_ to keep the code nicely
formatted. Be sure to install the commit hook locally to get these benefits::

    $ pip install -r requirements.txt
    $ pre-commit install

Development by `Caktus Consulting Group <http://www.caktusgroup.com/>`_.
