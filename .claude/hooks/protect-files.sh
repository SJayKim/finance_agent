#!/bin/bash
INPUT=$(cat)
FILE=$(echo "$INPUT" | grep -o '"file_path"[[:space:]]*:[[:space:]]*"[^"]*"' | sed 's/.*:[[:space:]]*"//;s/"$//')
if [[ "$FILE" == *.env* ]] || [[ "$FILE" == *secret* ]] || \
   [[ "$FILE" == *.pem ]] || [[ "$FILE" == *.key ]]; then
  echo "Blocked: protected file ($FILE)" >&2
  exit 2
fi
exit 0
