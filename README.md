# p4-gource

**p4-gource** is a Python script designed to fetch Perforce (P4) change logs and convert them into Gource-compatible format for visualization. It provides various features and options to customize the conversion process according to your requirements.

## Features

- **Perforce Log Fetching**: Automatically fetches Perforce change logs if not found locally.
- **Incremental Fetching**: Supports incremental fetching of Perforce logs, fetching logs by batch size, and skipping existing logs to minimize redundant fetching.
- **Flexible Path Filtering**: Allows inclusion and exclusion of specific paths using flexible wildcard expressions, supporting typical Perforce path syntax.
- **Gource File Generation**: Converts fetched Perforce logs into Gource-compatible format for visualization.
- **Automatic Gource Detection**: Automatically detects the presence of Gource executable and ensures its availability before execution.
- **Custom Gource Arguments**: Allows users to specify custom arguments for the Gource command for visualization customization.
- **Init View**: Automatically populates the gource view with the list of files present in the repository at the start revision.
- **Path Reduction**: Allows users to specify regular expressions in order to reduce paths and obtain a nicer visualization.

## Usage

1. **Installation**:
   - Ensure Python is installed on your system.
   - Clone or download the `p4-gource` script to your local machine.

2. **Requirements**:
   - Perforce command-line client (`p4`) should be installed and configured on your system. (https://www.perforce.com/downloads/helix-visual-client-p4v)
   - Gource should be installed and available in your system path. (https://gource.io/)
   - ffmpeg should be installed and available in your system path. (https://ffmpeg.org/download.html)

For windows, consider using Chocolatey (https://chocolatey.org/) to install gource and ffmpeg easily

3. **Configuration**:
   - Update Perforce server details (`P4PORT`) and user credentials (`P4USER`) in the script arguments or environment variables.

4. **Running the Script**:
   - Execute the script with appropriate options to fetch Perforce logs, convert them to Gource format, and visualize the project history.
   - Use command-line arguments to customize the script behavior according to your needs.

5. **Command-Line Arguments**:
   - `--p4-server <P4PORT>`: Specify the Perforce server address.
   - `--p4-user <P4USER>`: Specify the Perforce username.
   - `--start-rev <start_revision>`: Specify the starting Perforce revision to fetch logs from.
   - `--end-rev <end_revision>`: Specify the ending Perforce revision to fetch logs until.
   - `--batch-size <batch_size>`: Specify the batch size for incremental fetching of Perforce logs.
   - `--output <output_basename>`: Specify the radix use for all the files that will be output by this script.
   - `--gource-args "<custom_gource_arguments>"`: Specify custom arguments for the Gource command for visualization customization.

For more information or advanced use, see `--help`.

## Example Usage

```bash
python p4-gource.py --p4-server <P4PORT> --p4-user <P4USER> --start-rev <start_revision> --end-rev <end_revision> --batch-size <batch_size> --output <output_root_name> --gource-args "<custom_gource_arguments>"
```

## License
This script is licensed under the MIT License.

## Contributions
Contributions are welcome! If you encounter any issues, have suggestions, or want to contribute enhancements, please feel free to open an issue or submit a pull request.

## Acknowledgments  
Thanks to the original author, this was forked from https://github.com/max0x7ba/p4-gource.  
Thanks to Perforce for providing the Perforce version control system.  
Thanks to the Gource development team for creating the Gource visualization tool.  
Thanks to ChatGPT for providing most of the code faster than I could.  

