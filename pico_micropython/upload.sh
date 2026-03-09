#!/bin/bash

input="UPLOADLIST"

while IFS= read -r line; do 
    [[ -z "$line" ]] && continue

    mpremote cp ./$line :
done < "$input"
