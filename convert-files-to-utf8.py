import os

def convert_file_to_utf8_with_underscore(file_path):
    """
    Reads a binary file, attempts to decode it as UTF-8 replacing any undecodable bytes with '_',
    and writes the output back to the same file in UTF-8 encoding.

    Args:
    file_path (str): The path to the file to be converted.
    """
    try:
        # Read the file in binary mode
        with open(file_path, 'rb') as file:
            raw_data = file.read()
        
        # Decode the data, replace undecodable bytes with '_'
        decoded_data = raw_data.decode('utf-8', errors='replace')
        modified_data = decoded_data.replace('\ufffd', '_')
        
        # Write the modified data back to the file in UTF-8
        with open(file_path, 'w', encoding='utf-8') as file:
            file.write(modified_data)

        print(f"Converted {file_path} successfully.")
    
    except Exception as e:
        print(f"Failed to convert {file_path}: {e}")

def convert_all_logs_to_utf8(directory):
    """
    Converts all .log files in the specified directory to UTF-8 encoding.

    Args:
    directory (str): The directory to search for .log files and convert them.
    """
    for filename in os.listdir(directory):
        if filename.endswith(".log"):
            file_path = os.path.join(directory, filename)
            convert_file_to_utf8_with_underscore(file_path)

# Example usage: convert all .log files in the current working directory
current_directory = os.getcwd()
convert_all_logs_to_utf8(current_directory)