
# MAS-SLM-CVSS
Code and results files from the dissertation project

File	  What it does
Linear_Architecture/mvp_pipeline.py	  Defines the five worker agents and runs them in linear chain
Linear_Architecture/scoring_logic.py	  Checks the scorer's quotes against the CV and sets the label from its verdicts (Table 3.1)
Linear_Architecture/rag_criteria_agent.py	  Fetches the role's rubric from the index and passes it to the scorer
Hierarchical_Architecture/hier_pipeline.py	  Runs the orchestrator, which calls the workers as tools and writes their task notes
Simulations/api.py	  Serves the job descriptions and answers the credential and institution checks
harness/run_harness.py	  Runs each variant CV through the pipeline for each model and saves the result
harness/attack_report.py	  Compares attacked and clean runs and reports ASR, noise floor, control rate and McNemar tests.
harness/rq3_report.py	  Reports trigger activation, mandatory gate opening and ASR (Experiment 5)

How to run the code:

Install the dependency packages, start Ollama and the simulation API, then run each experiment. 
--scorer sets the scoring configuration, --arch sets the topology and --tag is (a label) used to a track the experiment results. Each run is appended to the results file as it finishes, so an interrupted run can be restarted

```
py -m pip install -r requirements.txt
ollama serve
py -m uvicorn Simulations.api:app --port 8000
 
set M=qwen3.5:4b,gemma4:e4b,llama3.1:8b

py harness/run_harness.py --models %M% --runs 1 --dataset-dir study/variants --tag study

py harness/run_harness.py --models %M% --runs 1 --dataset-dir study/variants --scorer model --tag study_model

py harness/run_harness.py --models %M% --runs 1 --dataset-dir study/variants --arch hierarchical --tag hier_study

py harness/run_harness.py --models %M% --runs 1 --dataset-dir study/variants --arch hierarchical --scorer model --tag hier_study_model ```

These four commands are Experiments 1 to 4. Set B uses the same commands with --dataset-dir study/variants_grayswan. Experiment 5 uses --dataset-dir study/variants_rag_poison with the poisoned addendum in the rubric index.
