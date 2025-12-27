## Submitting Tasks

Before submitting your task you must complete this checklist:


1. `tb run --agent oracle --task-id <task-id>`

    - and make sure it passes

2. `OPENAI_API_KEY=xxx tb tasks check <task-id>`

    - the checks don't all need to pass, but it is very likely that if you don't run this there is some ambiguity you missed. The main reason we run this is to make sure that you haven't missed some obvious task ambiguity and to make sure there isn't some obvious way for the model to cheat. 
    - include the output in your PR when you submit.

3. `caffeinate -i ./scripts_bash/run_model_comparison.sh --n-attempts 5 --dataset pw-test-2 --task-type cli`

    - note for this to work your credentials must be in `.credentials.yaml`, see `.credentials.yaml.example` for the format you need to use
    -  This will take a very long time to run, possibly 3 hours if the task keeps timing out, hence caffinate.
    - before running set the 'pw-test-2' dataset in `registry.json` to just your task id
    - task type is either cli (typical terminal bench) or code (code completion).
    - there must be at least 20% fails or your task is too easy.
    - When it is complete include the pass rate in your PR for each model

4. `uv run python scripts_python/analyze_task_failure.py <results-file> --api-key "xxx"`

    - do this at least once, it will show you why a one of the runs in that set of results failed.
    - You don't need to wait for the `run_model_comparison.sh` to finish fully. A single failure is enough, you will just have to find the `results.json` file
    - one of the runs has to have failed, so choose a results file with a failure
    - results file e.g. `runs/claude4_20251003_103633/results.json`
    - this is to make sure that failures are happening for reasonable reasons
    - include at least part of the printout in your pull request
    - instead of running this script you can just read the whole output, but this is probably a lot harder
