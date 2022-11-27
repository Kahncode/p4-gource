# Perforce to gource change log converter

Full story is at https://max0x7ba.blogspot.com/2010/05/visualize-perforce-change-log-with.html

## Usage

```
# Extract perforce log.
$ p4_head=$(p4 changes -m 1 | { read -a words && echo ${words[1]}; })
$ { for((i = 0; ++i <= p4_head;)); do p4 describe -s $i; done } > p4.log

# Convert perforce log to gource format.
$ ./p4-gource.py -p //depot/trunk -o trunk.gource p4.log

# Visualize.
$ gource --highlight-all-users trunk.gource
```
