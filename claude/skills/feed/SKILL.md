---
name: feed
description: Preload the files listed in the .foie_gras manifest into context
disable-model-invocation: true
allowed-tools: Bash(${CLAUDE_SKILL_DIR}/feed.sh)
---

!`${CLAUDE_SKILL_DIR}/feed.sh`

These files are attached with their current contents and count as read: use them directly, do not Read them again. If no task follows, reply `Ready.` and nothing else.

$ARGUMENTS
