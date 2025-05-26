import os

from da_vinci_cdk.application import (
    SideCarApplication,
)
from da_vinci_cdk.stack import Stack

from ratio_aws.agents.pricing.stack import RatioAWSPricingAgent


base_dir = Stack.absolute_dir(__file__)

ratio_app = SideCarApplication(
    app_entry=base_dir,
    app_name="ratio",
    deployment_id=os.getenv("RATIO_DEPLOYMENT_ID", "dev"),
    sidecar_app_name="ratio_aws_agents",
    log_level="DEBUG",
)

ratio_app.add_uninitialized_stack(RatioAWSPricingAgent)

ratio_app.synth()
