# Parsewave tbench dataset

> **IMPORTANT:** we perform force pushes to `parsewave/parsewave-contributor`. To stay up to date do `git pull --rebase`. DO NOT CHANGE ANYTHING IN THIS REPO FOR ANY REASON or the rebase will overwrite everything.

> If you are doing the Final Assignment right now you can skip this readme, it's very long and complex.

## Intro

We are building a custom private dataset for some of the world's leading AI labs based on [terminal bench](https://www.tbench.ai/).

Your job is to contribute as many good tasks as possible. This repo includes helpful tools to allow you to submit better tasks quicker.

## Setup

> INSTALLATION GUIDE FOR WINDOWS USERS:
>
> 1. Install WSL - https://apps.microsoft.com/detail/9PDXGNCFSCZV?hl=neutral&gl=RU&ocid=pdpshare
>
> 2. Make sure WSL is activated
>
> 3. Install docker desktop https://docs.docker.com/desktop/release-notes/
>    Full instalation guide:
>    https://docs.docker.com/desktop/setup/install/windows-install/

You have been given access to 2 repos:
This one `parsewave/parsewave-contributor`
And your personal one `parsewave/contributions-{GHNAME}` where GHNAME is your GitHub Name. This is for you to contribute tasks with.

Our recommendation is that you should clone your personal repo into the root of this repo `git clone github.com/parsewave/contributions-{GHNAME}`. This will allow you to access all our tooling which will make the task submission process much much quicker.

The key tool is `tb` which is our version of the terminal bench tool. You can run this by starting in this directory and running `uv run tb --help` this will tell you about the tool. You can use this to perform automated checks on the tasks you create in `contributions-{GHNAME}/contributor_tasks`.

You would need `OPENROUTER_API_KEY` for this setup. Alternative is `OPENAI_API_KEY` but commands will be slightly different. This README is focused only on using sole `OPENROUTER_API_KEY` variable.

In your personal `parsewave/contributions-{GHNAME}` repo should be .env file with `OPENROUTER_API_KEY`, use it only for contributing related purposes.

If you don't have the key - reach out to us to get the limited access key

## Prompts

You can use cli agents e.g. `claude-code` or `codex` to help you to build the task, HOWEVER `task.yaml` and `solution.sh` MUST be ALWAYS written by hand.

### Idea generation

We are currently working on a list of good task idea you can pick. For now we you can try this prompt to get some inspiration:

```
You need to come up with a task for terminal-bench dataset
Look at existing /tasks; https://www.tbench.ai/docs/task-ideas and https://www.tbench.ai/docs/task-quickstart for tasks suggestions. Pick the task which is not existing the dataset yet, not too easy but also potentially solvable by best models.
Task shouldn't have too much initial data. Data committed to the repo shouldn't exceed 1MB. Getting external data e.g cloning open source repo is fine, but shouldn't be excessive either, if setting up the task takes more than 5 minutes and more than 1GB disk space - this is too much

During the execution agent can't go to the internet

Ideally task instruction should be less than 100 words. solution.sh shouldn't be more than 200 lines of code. Agent should be able to finish the task in 1 minute, 5 minutes is hard stop. Instructions should be unambigous, if there are corner cases - provide exact expected behavior

Output should ONLY have 2 things:
1. similar to task.yaml field 'instructions' style instruction which can be used to create a task
2. the idea behind the task, specific things which are hard for LLM agents. Keep to a couple short points
```

### Building

Prompt to build the task:

```
Idea:
[IDEA GOES HERE]

General:
While completing the task, mark all executed steps in EXECUTION.md inside the created task folder.
Use green mark for executed and passing subtask including all checks. Yellow mark if there were concerns. Red if you weren't able to complete it

Step 1: Produce the draft task
Read quality_checker/models.py rules before creating the task to minimize future adjustments
Copy existing our_tasks/template-task to contributions-{GHNAME}/contributor_tasks with the appropriate short task name for the new idea

Do not add 'Terminal-Bench Canary String' nor author name
Never expose ports in docker-compose file, ports can collide with host system OS and it will prevent parallel runs

max_agent_timeout_sec 5 minutes is a hard stop

Protip: Keep Dockerfile with existing python (ghcr.io/laude-institute/t-bench/python-3-13:20250620) or install python in needed image. Install pytest inside Dockerfile too so then tests run faster
For simple case in run-tests.sh keep only:
'''
#!/bin/bash
pytest $TEST_DIR/test_outputs.py -v -rA
'''

Always use terminal bench docker image ghcr.io/laude-institute/t-bench/python-3-13:20250620 or ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
Apt dependencies should not have pinned version, but they should use fixed major versions packages e.g. postgresql-15
All pip dependencies should have pinned version.
All git related tasks which checks out public repo should have exact commit to checkout.

Do not leave clues inside visible to execution agent files when there is invalid data or corner cases

Step 2: Refine the task
Run `uv run tb run --agent oracle --task-id {TASK_ID} --dataset-path contributions-{GHNAME}/contributor_tasks` to check that solution.sh is working. Do green->red->green tests, if first pass works, change a test so it should fail, make sure it fails, then change back and run again

Run `uv run tb run --agent nop --task-id {TASK_ID} --dataset-path contributions-{GHNAME}/contributor_tasks` to check that if nothing is done tests don't pass. Run it in parallel with oracle

Run `uv run tb tasks check {TASK_ID} --model openrouter/openai/gpt-5 --tasks-dir contributions-{GHNAME}/contributor_tasks ` to get LLM based checks about quality of the task. Check can take up to 10 mins. This should be strictly passing or not applicable

Check that for gpt-oss-120B task mostly fails:
`uv run tb run --agent terminus-2 --model openrouter/openai/gpt-oss-120b --task-id {TASK_ID} --dataset-path contributions-{GHNAME}/contributor_tasks --n-attempts 5`
It's okay if it always fails

Check that for gpt-5 it passes at least once:
`uv run tb run --agent terminus-2 --model openrouter/openai/gpt-5 --task-id {TASK_ID} --dataset-path contributions-{GHNAME}/contributor_tasks --n-attempts 3`

After there are failures run `uv run tb tasks debug TASK_ID --run-id DATETIME(e.g. 2025-09-29__08-10-04) --model openrouter/openai/gpt-5` to check if it's fair failures or not

Model Gpt-5 is already released

Do this loop until all criteria are met. It's important to continue doing the loop. Run tasks in parallel when possible. If any of this steps don't pass, DON'T move to the next step
```

## Submitting PR

When you submit a task the first thing we will do is run several automated checks on it. If any of them fail, you will need to alter the task to make it pass.

### Basic checks

The Oracle must pass i.e. the solution.sh must actually solve the task.

```
uv run tb run --agent oracle --task-id {TASK_ID} --dataset-path contributions-{GHNAME}/contributor_tasks
```

The NOP (no-op, which does nothing) must fail:

```
uv run tb run --agent nop --task-id {TASK_ID} --dataset-path contributions-{GHNAME}/contributor_tasks
```

### Quality Check

```
uv run tb tasks check {TASK_ID} --tasks-dir contributions-{GHNAME}/contributor_tasks --model openrouter/openai/gpt-5
```

If there are Failed checks, provide reasonable explanation why it doesn't need to be fixed. If we see failed checks on our end with no explanation we will ask for the explanation before we accept the task.

### Agent checks

These are the exact agent checks we will perform, so to be sure your submission is accepted you should stick as close to them as possible.

gpt-oss 120b must fail at least once, mostly failing or always failing is even better:

```
uv run tb run --agent terminus-2 --model openrouter/openai/gpt-oss-120b --task-id {TASK_ID} --dataset-path contributions-{GHNAME}/contributor_tasks --n-attempts 5
```

And GPT-5 must pass at least once out of 3 times:

```
uv run tb run --agent terminus-2 --model openrouter/openai/gpt-5 --task-id {TASK_ID} --dataset-path contributions-{GHNAME}/contributor_tasks --n-attempts 3
```

Analyze the failures with:

```
uv run tb tasks debug {TASK_ID} --tasks-dir contributions-{GHNAME}/contributor_tasks --run-id e.g(2025-10-15__06-18-10) --model openrouter/openai/gpt-5
```

### PR Structure

PRs should be in your personal repo `contributions-{GHNAME}` under folder `contributor_tasks`

To submit create a NEW BRANCH with the task name for each task, and then create PR to 'review' branch.

The structure of the PR text should be:

```
I ran Oracle + NOP

I ran quality checks: NO FAIL/ X FAILED
REASONABLE EXPLANATION WHY FAILED CHECKS GOES HERE IF ANY

I ran agents:
terminus-2 + gpt-oss-120b: x/5 pass - explanation why agent failed

terminus-2 + gpt-5: x/3 pass - explanation why agent failed

Attachment: Screenshot of `tb tasks check` result. (Copy pasting the table works too)
```

> **IMPORTANT:** Always craete a new branch for a new task! If your PR description doesn't have that format, your tasks might be never reviewed!!!

# terminal-bench

for more information about terminal bench visit [https://www.tbench.ai](https://www.tbench.ai). This repo is a fork of the terminal bench repo so a lot of their documentation will apply. Some important differences:

- `our_tasks` contains tiny example subset of the tasks we have created, and `tasks` contains most of the original terminal bench tasks, for you to use as inspiration.
- we have made some small improvements to the `tb` tool compared to the original terminal bench repo.
