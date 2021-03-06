## Guide for running the iperf3 and sockperf microbenchmarks

### Configuration

None other than general ../env/README.md setup (run ansible for
env/packages.yml and code/bess/env/packages.yml)

### Running the experiment

The "results", "results/sockperf", and "configs" directories need to exist.
```
mkdir results configs results/sockperf
```

#### Running a single configuration by hand:

1. Start sinks by hand
```./tc_test_start_progs.py --dir sink --configf configs/test.yaml```

2. Start srcs by hand
```./tc_test_start_progs.py --dir src --configf configs/test.yaml```

#### Running configurations from a script:

1. Generate the configs
```./gen_tc_test_configs.py```

2. Run the scripts
```
./run_bess.sh
./run_bess_rl.sh
```

Note: these scripts are currently very hard-coded still.  I don't have a reason to make
  this more general yet though.

3. Parse and plot the output

Useful commands:
```
./results_scripts/plot_tenant_tput_ts.py --results results/tputs.bess-sq..yaml
./results_scripts/gen_latency_ts.py --sq results/src.tctest.tctest_conf1.bess-sq.1.1.yaml --mq results/src.tctest.tctest_conf1.bess-mq.1.1.yaml --loom results/src.tctest.tctest_conf1.bess-tc.1.1.yaml --qpf results/src.tctest.tctest_conf1.bess-qpf.1.1.yaml --outf results/tctest_latency_ts.yaml
./results_scripts/plot_latency_ts.py --results results/tctest_latency_ts.yaml --figname results/tctest_latency_ts.pdf

for i in {1..20}
do
    ./results_scripts/gen_latency_ts.py --sq results/src.tctest.tctest_conf1.bess-sq.$i.1.yaml --mq results/src.tctest.tctest_conf1.bess-mq.$i.1.yaml --loom results/src.tctest.tctest_conf1.bess-tc.$i.1.yaml --qpf results/src.tctest.tctest_conf1.bess-qpf.$i.1.yaml --outf results/tctest_latency_ts.$i.yaml
done

./results_scripts/gen_cpu_util_ts.py --sq results/src.tctest.tctest_conf1.bess-sq.1*.yaml --mq results/src.tctest.tctest_conf1.bess-mq.1*.yaml --qpf results/src.tctest.tctest_conf1.bess-qpf.1*.yaml --loom results/src.tctest.tctest_conf1.bess-tc.1*.yaml --outf results/tctest.cpu_util.yaml
```

#### 40G Debugging Notes

