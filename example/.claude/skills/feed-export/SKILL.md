---
name: feed-export
description: Preload the files listed in .foie_gras/export
disable-model-invocation: true
argument-hint: [prompt]
arguments: [first, second]
allowed-tools: Bash(${CLAUDE_SKILL_DIR}/../feed/feed.sh export)
---

!`${CLAUDE_SKILL_DIR}/../feed/feed.sh export`

These files are attached with their current contents and count as read: use them directly, do not Read them again. The task is in the command arguments; if there are none, reply `Ready.` and nothing else.

<!-- $second -->
