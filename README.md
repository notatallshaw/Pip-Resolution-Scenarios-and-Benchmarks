# Introduction

This is a series of scripts that represents what I often do manually to
test changes to pip's resolution algorithm.

# Running the scripts

The script is PEP 723 compliant, so you can use any tool that can run
PEP 723 scipts. Here are examples using uv:

    uv run scenarios.py --pip-version 24.2
    uv run scenarios.py --github-repo "notatallshaw/pip" --git-commit c4157d8dfb2823fc967549ccca08c150ab3df98b
    uv run compare.py --pip-version-1 24.2 --github-repo-2 "notatallshaw/pip" --git-commit-2 c4157d8dfb2823fc967549ccca08c150ab3df98b

# What is it measuring?

The idea is to measure the resolution in terms of the number of, the
number of unique sdists it had to visist (io and build cost), the number of
unique wheels it had to visit (io cost), the total number of time is visited
a package or a requirements or pinned a package (cpu cost), and the total
number of "resolution rounds" (roughly the number of "steps" the resolver
had to take).

# What is it not measuring?

The script it not measuring wall clock time. While it may be added in the
future it is non-trivial, as it's only worth comparing runs on the same
machine that were run when it is in similiar state.

# Why not use `pip-resolver-benchmarks`?

[pip-resolver-benchmarks](https://github.com/pradyunsg/pip-resolver-benchmarks) is
a great tool but currently is unmaintained and is focused on wall clock time.

# To Dos

 * Rich logging, that shows progress of long pip installs
 * More metrics around what counts as a "better" install and resolution
