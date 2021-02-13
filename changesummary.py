from enum import IntEnum
import json
from multiprocessing import Pool
import os
import pandas as pd
import numpy as np

BRANCH_ARTIFACTS_DIR = 'branch/'
MAIN_ARTIFACTS_DIR = 'main/'
MULTIPROCESSING_NUM_PER_BATCH = 5
MULTIPROCESSING_NUM_AGENTS = 10

class ChangeType(IntEnum):
    UNKNOWN = 0
    DELETED = 1
    ADDED = 2
    CHANGED = 3

class ArtifactsDirDoesNotExist(ValueError):
    """Raised when the artifacts directory doesn't exist.
    """
    pass

class FileListCannotBeEmpty(ValueError):
    """Raised when a file_list is empty.
    """
    pass

class ChangeSummary:
    """Represents the change summary between 2 directories containing \
        artifacts.
    """
    def __init__(self, new_artifacts_dir, current_artifacts_dir, file_list):
        """Initializes an instance of a ChangeSummary.

        Args:
            new_artifacts_dir: The relative path to the directory with the new \
                discovery artifacts.
            current_artifacts_dir: The relative path to the directory with the \
                current discovery artifacts.
            file_list: A list of strings containing files to analyze.
        """
        if file_list is None:
            raise FileListCannotBeEmpty("file_list should not be empty")

        self._file_list = file_list
        self._new_artifacts_dir = new_artifacts_dir
        self._current_artifacts_dir = current_artifacts_dir
        self._raise_if_artifacts_dir_not_found(self._new_artifacts_dir)
        self._raise_if_artifacts_dir_not_found(self._current_artifacts_dir)

    def _raise_if_artifacts_dir_not_found(self, directory):
        """Raises ArtifactsDirDoesNotExist if the `directory` doesn't exist

        args:
            directory: The relative path to the `directory` with the artifacts.
        """
        if (not os.path.exists(directory)):
            raise ArtifactsDirDoesNotExist("Artifacts directory does not " \
                                            " exist : {0}".format(directory))

    def _load_json_to_dataframe(self, directory, filename):
        """Returns a pandas dataframe from the json file provided.

        args:
            directory: The relative path to the `directory` with the artifacts.
            filename: The name of the discovery artifact to parse.
        """

        dataframe_doc = None
        file_path = os.path.join(directory, filename)
        if os.path.exists(file_path):
            with open(file_path, 'r') as f:
                dataframe_doc = pd.json_normalize(json.load(f))
        return dataframe_doc

    def _get_discovery_differences(self, filename):
        """Returns a pandas dataframe which contains the differences with the
        current and new discovery artifact directories, corresponding to the
        file name provided.

        args:
            filename: The name of the discovery artifact to parse.
        """
        current_doc = self._load_json_to_dataframe(self._current_artifacts_dir,
                                                filename)
        new_doc = self._load_json_to_dataframe(self._new_artifacts_dir,
                                                filename)

        combined_docs = pd.concat([current_doc, new_doc],
                                    keys=['CurrentValue',
                                            'NewValue']).transpose()
        combined_docs.columns = combined_docs.columns.droplevel(1)

        if 'CurrentValue' not in combined_docs.columns:
            combined_docs['CurrentValue'] = np.nan
        if 'NewValue' not in combined_docs.columns:
            combined_docs['NewValue'] = np.nan

        docs_diff = combined_docs[
            combined_docs['CurrentValue'] != combined_docs['NewValue']
            ]
        docs_diff = docs_diff.rename_axis('Key').reset_index()
        docs_diff[['Name', 'Version']] = filename.split('.')[0:2]

        deleted_condition = docs_diff['NewValue'].isnull()
        added_condition = docs_diff['CurrentValue'].isnull()

        docs_diff['ChangeType'] = np.where(deleted_condition,
                                            ChangeType.DELETED,
                                            np.where(added_condition,
                                                        ChangeType.ADDED,
                                                        ChangeType.CHANGED))

        docs_diff = docs_diff[~docs_diff['Key'].str.contains('|'.join(
                                                    self._get_keys_to_ignore()),
                                                    case=False)]
        docs_diff.drop(['NewValue', 'CurrentValue'], axis = 1, inplace=True)
        return docs_diff

    def _build_summary_message(self, api_name, is_feature, is_breaking):
        """Returns a string containing the summary for a given api. The string
            returned will be in the format `fix(<api_name>): update the API`
            when `is_feature=False` and `feat(<api_name>)!: update the API`
            when `is_feature=True`. The exclamation point only exists in the
            string when `is_breaking=True`.

            args:
                api_name: The name of the api to include in the summary
                is_feature: If True, include the prefix `feat` otherwise use
                    `fix`
                is_breaking: If True, include an exclamation point prior to the
                    colon in the summary message to indicate that this is a
                    breaking change.
        """
        commit_type = 'feat' if is_feature else 'fix'
        breaking_change_char = '!' if is_breaking else ''
        return '{0}({1}){2}: update the api\n'.format(api_name, commit_type, \
                                                        breaking_change_char)

    def _get_keys_to_ignore(self):
        """ Returns keys to ignore as an array of strings.
            args: None
        """
        keys_to_ignore = [
            'description',
            'documentation',
            'enum',
            'etag',
            'revision',
            'title'
            'url',
            'rootUrl'
            ]
        return keys_to_ignore

    def _get_summary_from_dataframe(self, dataframe):
        """Returns an array of strings which contain summary information about
            changes made to discovery artifacts based on the provided dataframe.
            args:
                dataframe: a pandas dataframe containing summary change
                    information for all discovery artifacts
        """
        dataframe['IsFeature'] = np.where( \
            (dataframe['ChangeType'] == ChangeType.DELETED) | \
                (dataframe['ChangeType'] == ChangeType.ADDED), True, np.nan)

        dataframe['IsBreaking'] = np.where( \
            (dataframe['ChangeType'] == ChangeType.DELETED), True, np.nan)

        dataframe['IsFeatureAggregate'] = dataframe.groupby( \
            'Name').IsFeature.transform(lambda x : x.any())

        dataframe['IsBreakingAggregate'] = dataframe.groupby(\
            'Name').IsBreaking.transform(lambda x : x.any())

        dataframe['Summary'] = np.vectorize(self._build_summary_message)\
                                            (dataframe['Name'],
                                            dataframe['IsFeatureAggregate'],
                                            dataframe['IsBreakingAggregate'])

        return [summary_msg for summary_msg in dataframe.Summary.unique()]

    def _get_verbose_changes_from_dataframe(self, dataframe):
        """Returns an array of strings which contain verbose information about
            changes made to discovery artifacts based on the provided dataframe.
            args:
                dataframe: a pandas dataframe containing verbose change
                    information for all discovery artifacts
        """
        verbose_changes = []
        change_type_groups = dataframe[['Name','Version','ChangeType','Key']].groupby(['Name','Version','ChangeType'])

        lastApi = ''
        lastVersion = ''
        lastType = ChangeType.UNKNOWN

        for name, group in change_type_groups:
            currentApi = name[0]
            currentVersion = name[1]
            currentType = name[2]

            if lastApi != currentApi or lastVersion != currentVersion:
                verbose_changes.append('\n\n#### {0}:{1}\n\n'.format(name[0],name[1]))
                lastApi = currentApi
                lastVersion = currentVersion
                lastType = ChangeType.UNKNOWN

            if (currentType != lastType):
                if currentType == ChangeType.DELETED:
                    verbose_changes.append("\nThe following keys were deleted:\n")
                elif currentType == ChangeType.ADDED:
                    verbose_changes.append("\nThe following keys were added:\n")
                else:
                    verbose_changes.append("\nThe following keys were changed:\n")

                lastType = currentType
                verbose_changes.extend(['- {0}\n'.format(key) for key in group['Key']])

        return verbose_changes

    def detect_discovery_changes(self):
        """Prints a summary of the changes to the discovery artifacts to the
            console.
            args: None
        """
        result = pd.DataFrame()

        with Pool(processes=MULTIPROCESSING_NUM_AGENTS) as pool:
            result = result.append(pool.map(self._get_discovery_differences,
                                                self._file_list,
                                                MULTIPROCESSING_NUM_PER_BATCH))

        result = result.sort_values(by=['Name','Version','ChangeType','Key'],
                                        ascending=True)
        print(''.join(self._get_summary_from_dataframe(result)))
        print(''.join(self._get_verbose_changes_from_dataframe(result)))


with open(''.join([BRANCH_ARTIFACTS_DIR,'/changed_files'])) as f:
    file_list_raw = f.read().splitlines()
    file_list = [filename.rsplit('/',1)[-1] for filename in file_list_raw]
    ChangeSummary(BRANCH_ARTIFACTS_DIR, MAIN_ARTIFACTS_DIR,
                    file_list).detect_discovery_changes()



