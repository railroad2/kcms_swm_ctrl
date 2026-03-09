#!/bin/bash

copyall() {
    path=$1
    flist=`mpremote fs ls ${path} | tr -d '\r' | grep -v ":" | awk '{ print $2 }'`

    for fn in ${flist[@]}; do
        if [[ "${fn}" == */ ]]; then
            #echo ${fn}
            mkdir ${fn}
            copyall ${fn}
        else
            #echo $1${fn}
            mpremote fs cp :$1${fn} $1
        fi
    done
}


copyall ./
