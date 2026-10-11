---
name: feed
description: Preload the files listed in .foie_gras/default, or in .foie_gras if it is a file
disable-model-invocation: true
argument-hint: [prompt]
arguments: [first, second]
allowed-tools: Bash(${CLAUDE_SKILL_DIR}/feed.sh)
---

!`${CLAUDE_SKILL_DIR}/feed.sh`

These files are attached with their current contents and count as read: use them directly, do not Read them again. The task is in the command arguments; if there are none, reply `Ready.` and nothing else.

<!-- $second -->
