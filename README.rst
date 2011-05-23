FabulAWS
========

A Python tool for creating and interacting with ephemeral AWS resources.

Requirements
============

Dependencies are listed in the accompanying PIP requirements file.  To install
them, run the following command::

    pip install -r requirements.txt

Usage
=====

The idea behind FabulAWS is to let you create ephemeral EC2 instances using
a context manager in Python, execute some work on that instance, and not worry
about manually cleaning up the created resources.  Typical workflow looks like
this::

    from fabulaws.ec2 import MicroLucidInstance
    
    with MicroLucidInstance(my_api_key_id, my_secret_key):
        run('uname -a')

If needed, you can extend the instance classes defined in the ``fabulaws.ec2``
module as needed to further customize the instance before presenting it as
a context manager.  To do so, simply extend the ``setup()`` and ``cleanup()``
methods in one of the existing classes.

