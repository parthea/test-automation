#!/bin/bash
git config --global user.name 'Yoshi Automation'
git config --global user.email 'yoshi-automation@google.com'

while read api;
do
    name=`echo $api | cut -d '.' -f 1`
    API_SUMMARY_PATH=temp/$name.verbose
    if [ -f "$API_SUMMARY_PATH" ]; then
        git add 'googleapiclient/discovery_cache/documents/'$name'.*.json'
        git add 'docs/dyn/'$name'_*.html'
        commitmsg=`cat $API_SUMMARY_PATH`
        git commit 'googleapiclient/discovery_cache/documents/'$name'.*.json' 'docs/dyn/'$name'_*.html' -m "$commitmsg"
    fi
done < changed_files
exit 0
