#!/bin/bash

# Create the jsons directory if it doesn't exist
rm -rf jsons
mkdir -p jsons

# Find all directories containing JSON files
for dir in $(find . -type f -name "*.json" -exec dirname {} \; | sort | uniq)
do
  echo "Processing directory: $dir"
  
  # Create an output filename based on the directory name
  # dir_name=$(basename "$dir")
  # output_file="jsons/${dir_name}.json"
  
  dir_parts=(${dir//\// })  # Split the path by '/'
  
  # If we have a path with at least 3 parts (like ./xl170/4m_hf3fs_xfs_usrbio_xl170_18/4M)
  if [ ${#dir_parts[@]} -ge 3 ]; then
    target_dir="${dir_parts[2]}"  # Get the second directory name (index 2)
  else
    # Fallback to the immediate directory name
    target_dir=$(basename "$dir")
  fi
  output_file="jsons/${target_dir}.json"

  # Call the Python script for each directory
  python extract_fio_to_json.py "$dir" -o "$output_file"
  
  echo "Completed processing $dir -> $output_file"
  echo "----------------------------------------"
done

echo "All directories processed!"