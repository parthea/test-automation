#!/bin/bash
while read api;
do
    name=`echo $api | cut -d '.' -f 1`
    git config --global user.name 'Yoshi Automation'
    git config --global user.email 'yoshi-automation@google.com'
    (cd googleapiclient/discovery_cache/documents && git add $name.*.json)
    (cd docs/dyn && git add $name_*)
    commitmsg=`cat temp/$name.verbose`
    git commit -m "$commitmsg"
    git push
done < changed_files

