# Ideas

Just a set of ideas to consider.

## What is the problem this _needs_ to solve?

There are different ways to deploy different technologies to the cloud. Provide an interface which allows you to deploy these differing technologies with a single approach.

## Assessments

### The good

#### Single interface for multiple IaC solutions

* Simplified deployment of multiple dependent stacks across various environments, accounts, and regions.
* Support for integration between multiple Infrastructure as Code (IaC) technologies through a single script/configuration, providing a convenient way to connect inputs and outputs between different IaC solutions.
* Cross-framework deployment support.
* IaC agnosticism. Support for main IaC tools in a single configuration.

#### Parameter lookup tables

* Externalizing key parameters using lookups without creating rigid dependencies.
* Simple parameterization of IaC templates.
* Use of global and environmental variables standardizing the deployments

#### Improvements over base tooling

* Implementation of guardrails for environment deployments, including standardization of Terraform versions at the runtime (big problem solution when using vanilla Terraform)
* Standardization and reusability of code, particularly for CloudFormation.
* Support for Jinja templating, making creation of conditional statements and loops in IaC templates possible.
* Useful pre/post deployment hooks for customization.

#### Other

* Ease of setting up CI/CD pipelines using Runway.

### The bad

#### Adoption

* Limited adoption by customers, making it challenging to promote the tool.
* Lack of maintenance.

#### Learning curve

* Lack of comprehensive tutorials and examples in the documentation.
* Difficulty in understanding and utilizing various features.
* Insufficient internal support.
* Painful process of transitioning between major versions due to the required code updates.
* Runway documentation is primarily geared towards developers and can be difficult for DevOps and infrastructure professionals to comprehend and use effectively.

#### Other

* The tool is attempting to encompass too many functions, resulting in certain features that are not widely used but significantly increase the project's complexity.
* Poor handling of errors, such as dropping raw Python exceptions instead of providing user-friendly error messages (partially resolved).

### To improve

#### Support

* Continuation of maintenance and development of new features.
* Creation of a roadmap outlining future features.
* Introduction of better internal support similar to the support received before the departure of the Runway development team.
* Improvement and expansion of tutorial-style documentation, including additional content and examples demonstrating the usage of hooks and creating demos.
* Building a library of reusable templates.

#### Streamlining

* Focus on core functionality and removal of unnecessary features that hinder the tool's maintainability and support.
* Rewriting the tool using Go to eliminate the dependency on the Python interpreter.

#### New features

* Addition of multi-cloud support.
  * What does this actually mean?

## Open questions

* Is Runway a CLI, or a _system?_
* What are the most useful _specific_ features?
* What are the existing papercuts?
* ~~Kubernetes is a platform that you deploy atop.~~
  * ~~Does Runway set up the platform?~~
  * ~~Does it set up the things that drive the platform?~~
  * ~~How does Runway converge with ArgoCD?~~
* Is there a CI component?
  * Which CI systems should we support?
* What is "the standardized query syntax" in `runway.cfngin.*`?
* How does this compare to [Atmos](https://atmos.tools)?
  * Terraform/OpenTofu
  * DevContainers
  * Ansible
  * Packer
  * Helmfile

## Core tenets (unless you know better ones)

* Make the lives of the users better.
  * Don't repeat yourself.
  * Leverage strong, repeatable patterns.
  * Convention over configuration.
  * Context over consistency.
* You can't please everybody all the time, so don't try to.
  * Aim for the 80-90% use case.
  * Don't try to solve the remaining 10-20%.
* Unix philosophy
  * Write programs that do one thing and do it well.
  * Write programs to work together.
* Focus on the deployment step.
  * Other tools can fill-in the linting, static analysis, and testing steps.

## Deployment types

### Technologies

* [AWS CloudFormation]
  * [AWS CDK]
  * [AWS Serverless Application Model][AWS SAM]
* [Terraform]/[OpenTofu]
  * [Amazon S3] + [CloudFront]
* ~~Kubernetes~~
* [Serverless Framework]

### Clouds/services

* [AWS] (Terraform/OpenTofu, CloudFormation, S3, RDS, etc.)
* [Azure] (Terraform/OpenTofu, etc.)
* [Cloudflare] (Terraform/OpenTofu, Cloudflare workers, R2, D1, etc.)
* [GCP] (Terraform/OpenTofu, etc.)

### CI/CD integration

What is this integration, exactly?

* GitHub
* GitLab
* BitBucket
* CircleCI

## Feature ideas

* Guardrails for deployments
  * Terraform version standardization at runtime
    * How? tfenv? tfswitch? tenv?

* Custom plugin support
  * Not convinced this is a good idea at the moment.
  * If we can solve this with hooks, then fine.
  * Do we solve this with HashiCorp's gRPC model?

* Dependency Management: What does this mean?

* Parameter Lookups
  * Externalize key parameters using lookups (Amazon Parameter Store, equivalents in Azure, GCP, and Cloudflare)
  * If we _need_ something local, look at sqlite/duckdb/whatever

* Interoperability
  * Support for different IaC technologies through a single config.
  * Focus on the ones with the most usage.

* Pre/post deployment hooks
  * At what level? Per deployment? Per stage? Larger scope? Smaller scope?

* Prepend module name to output for parallel deployments.
  * Capture + modify + print
  * Streaming buffer
  * Colors?

## Development changes (Python)

* Publicly state that we only support Python versions which are not EOL.
  * Dropping EOL versions of Python is NOT a breaking change for Runway.
  * The lowest supported version of Python is not necessarily _our_ minimum.
  * Porting to Go will eliminate this consideration all-together.

* Stronger linting standards with newer-generation tooling
  * [hk] (replaces pre-commit)
  * [rumdl] (replaces markdownlint)
  * [task] (replaces make)
  * Add [shellcheck], [shfmt] (shell code linting)
  * Add [editorconfig] + [editorconfig-checker] (broad code formatting)
  * Add [taplo] (format TOML)
  * Add [lychee] (validate links in files)
  * Add [govulncheck] + [osv-scanner] + [trivy] (security scanning)

* Adopt Rust-based Python tooling
  * [uv] (replaces pip, Poetry, pipx)
  * [ruff] (replaces flake8 and many more)
  * [tryke] (replaces pytest)
  * [zuban] (replaces mypy)

## Development changes (Go)

* Migrate to Go, one feature at a time.
  * Maintain existing v2 (Python) alongside v3 (Go) until feature parity is achieved.
  * Go = improved performance + concurrency + no runtime dependencies
* Which features would benefit from concurrency?
  * AWS CDK — [Don't fail on diff](https://runway.readthedocs.io/stable/cdk/configuration.html#aws-cdk-enablediffnofail).
  * AWS CDK — [Run build steps in parallel](https://runway.readthedocs.io/stable/cdk/advanced_features.html#build-steps) (opt-in)
    * Support updated YAML syntax which can name tasks and specify dependencies.
  * [Plugin system](https://github.com/hashicorp/go-plugin)
    * [go-embed-python](https://github.com/kluctl/go-embed-python) for running custom Python CFNgin plugins.
    * Maybe we add support for new services using plugins?
      * Want AWS CDK and Serverless? Just install those plugins!
* Support same config formats as [Viper](https://github.com/spf13/viper).
  * JSON
  * TOML
  * YAML
  * INI
  * .env
  * Java Propeties
* log_formats
  * kv-string format: `time=2023-03-15T13:00:11.333+01:00 level=INFO msg="Info message"`
  * JSON format: `{"time":"2023-03-15T13:00:11.333+01:00","level":"INFO","msg":"Info message"}`
* Lookup system (feature)
  * Don't try to lookup values from state files or whatever on-demand (need to look at implementation).
  * Create a registry where these values are written by default; read from the registry.

## Development changes (AI)

* Adopt AI tooling and guardrails in the codebase
  * [Agent Toolkit for AWS](https://aws.amazon.com/products/developer-tools/agent-toolkit-for-aws/)
  * [Kirograph](https://github.com/davide-desio-eleva/kirograph)
  * Custom steering definitions
  * Instruct agents to use deterministic checks to validate code writing.

## How CFNgin seems to work

* It _seems_ as though CFNgin is an abstraction layer over Troposphere.
* A LOT of work went into supporting CloudFormation.
* YAML document with support for anchors and merges.
* CloudFormation pushes CloudFormation templates (JSON/YAML) to S3, then the CloudFormation engine reads from there.
  * AWS CLI works like that.
  * AWS SAM works like that.
  * Terraform deploying CloudFormation templates works like that.
  * Not sure how CloudFormation Rain works, but _probably_ similar.
  * Need an S3 bucket + region.
* Lookup system — For [CFNgin](https://runway.readthedocs.io/stable/cfngin/lookups/index.html) and [Runway itself](https://runway.readthedocs.io/stable/lookups/index.html)
* [Remote sources](https://runway.readthedocs.io/stable/cfngin/remote_sources.html) — Docs don't explain what this is for.
* [Hook system](https://runway.readthedocs.io/stable/cfngin/hooks/index.html) — Pre/post events.
* [Templating](https://runway.readthedocs.io/stable/cfngin/templates.html) with Jinja2
* Blueprints — For both [Troposphere](https://github.com/cloudtools/troposphere) and [Runway itself](https://github.com/rackspace/runway/tree/master/runway/blueprints).
  * Can we simply ship a compiler for these (separate from Runway 3) that compiles the Python code into CloudFormation YAML/JSON?
  * Runway 3 just worries about deploying the finished templates to CloudFormation?
* [Persistent dependency graph](https://runway.readthedocs.io/stable/cfngin/persistent_graph.html)
  * Stored in S3.
  * Supports locking — similar to [Terraform's locking S3 backend](https://developer.hashicorp.com/terraform/language/backend/s3).
* Supports IAM roles for deployments (good)
  * How does CI assume this role?

## How static site configuration seems to work

* Takes a YAML config and generates a CloudFormation template.
* S3 + CloudFront + Cognito + Lambda@Edge + ACM + WAF
* Candidate for removal?

## Documentation

* We need to lower the entry bar. Get more technical people onboard.
* Focus on users - CEs/SAs - not only developers will help with adoption - target engineers that are not familiar with OOLs (what are CEs, SAs, and OOLs?)
* QuickStarts - for the deployment of infra starting with simple deployments to complicated
* Library of reusable templates and base projects
* Demos

## Migration story

* Support same config file definition.
* Can we support [Jinja2] templates as-is?
* Support Go templates as well.
* Opt-in tooling to help migrate from Jinja2 to Go templates.

## Will not do

* ~~Standardize not only on deployment but also on best practices, linting, unit tests.~~ (hk)
* ~~Integration of static code analysis tooling~~ (hk)
* ~~Integration with TF supported linting~~ (hk)

[Amazon S3]: https://aws.amazon.com/s3/
[AWS CDK]: https://cdk.dev
[AWS CloudFormation]: https://aws.amazon.com/cloudformation/
[AWS SAM]: https://aws.amazon.com/serverless/sam/
[AWS]: https://aws.amazon.com
[Azure]: https://azure.com
[Cloudflare]: https://www.cloudflare.com/products/
[CloudFront]: https://aws.amazon.com/cloudfront/
[editorconfig-checker]: https://editorconfig-checker.github.io
[editorconfig]: https://editorconfig.org
[GCP]: https://cloud.google.com
[govulncheck]: https://go.dev/doc/tutorial/govulncheck
[hk]: https://hk.jdx.dev
[Jinja2]: https://pypi.org/project/Jinja2/
[lychee]: https://lychee.cli.rs
[OpenTofu]: https://opentofu.org
[osv-scanner]: https://google.github.io/osv-scanner/
[ruff]: https://docs.astral.sh/ruff/
[rumdl]: https://rumdl.dev
[Serverless Framework]: https://serverless.com
[shellcheck]: https://shellcheck.net
[shfmt]: https://github.com/mvdan/sh
[taplo]: https://taplo.tamasfe.dev
[task]: https://taskfile.dev
[Terraform]: https://terraform.io
[trivy]: https://trivy.dev
[tryke]: https://tryke.dev
[uv]: https://docs.astral.sh/uv/
[zuban]: https://zubanls.com
