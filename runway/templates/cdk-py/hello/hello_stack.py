"""Hello stack."""

# ruff: noqa
from aws_cdk import aws_iam as iam  # type: ignore[import-not-found]
from aws_cdk import aws_sns as sns  # type: ignore[import-not-found]
from aws_cdk import aws_sns_subscriptions as subs  # type: ignore[import-not-found]
from aws_cdk import aws_sqs as sqs  # type: ignore[import-not-found]
from aws_cdk import core  # type: ignore[import-not-found]

from .hello_construct import HelloConstruct


class MyStack(core.Stack):
    """My stack."""

    def __init__(self, scope: core.Construct, id: str, **kwargs) -> None:
        """Instantiate class."""
        super().__init__(scope, id, **kwargs)

        queue = sqs.Queue(self, "MyFirstQueue", visibility_timeout=core.Duration.seconds(300))

        topic = sns.Topic(self, "MyFirstTopic", display_name="My First Topic")

        topic.add_subscription(subs.SqsSubscription(queue))

        hello = HelloConstruct(self, "MyHelloConstruct", num_buckets=4)
        user = iam.User(self, "MyUser")
        hello.grant_read(user)
