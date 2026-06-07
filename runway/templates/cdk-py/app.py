"""Sample app."""

# ruff: noqa
from aws_cdk import core  # type: ignore[import-not-found]
from hello.hello_stack import MyStack  # type: ignore[import-not-found]

app = core.App()
MyStack(app, "runway-cdk-py-sample")

app.synth()
