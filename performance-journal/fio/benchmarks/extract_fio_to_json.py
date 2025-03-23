import os
import json
import glob
import argparse
import sys

def extract_fio_data(directory_path, output_file):
    # Dictionary to store the combined data
    combined_data = {}
    
    # Find all JSON files in the directory
    files = glob.glob(os.path.join(directory_path, "*.json"))
    if not files:
        # If no JSON files, try text files that might contain JSON
        files = glob.glob(os.path.join(directory_path, "*.txt"))
    
    if not files:
        print(f"No JSON or text files found in {directory_path}")
        return
    
    print(f"Processing {len(files)} files...")
    
    # Process each file
    for file_path in files:
        try:
            with open(file_path, 'r') as file:
                file_content = file.read()
                
                # Parse JSON data from the file
                try:
                    data = json.loads(file_content)
                    
                    # Extract the important benchmark information
                    if 'jobs' in data:
                        file_name = os.path.basename(file_path)
                        test_type = None
                        
                        # Try to determine test type from jobs
                        if data['jobs'] and len(data['jobs']) > 0:
                            job = data['jobs'][0]
                            if 'job options' in job and 'rw' in job['job options']:
                                test_type = job['job options']['rw']
                            
                            # Get block size and thread info
                            bs = job['job options'].get('bs', 'unknown')
                            iodepth = job['job options'].get('iodepth', 'unknown')
                            numjobs = job['job options'].get('numjobs', 'unknown')
                            
                            # Create structure for this test if it doesn't exist
                            if test_type not in combined_data:
                                combined_data[test_type] = {}
                            
                            if iodepth not in combined_data[test_type]:
                                combined_data[test_type][iodepth] = {}
                                
                            if numjobs not in combined_data[test_type][iodepth]:
                                combined_data[test_type][iodepth][numjobs] = {}
                            
                            # Extract performance metrics
                            metrics = {}
                            
                            # Bandwidth in GB/s
                            if 'read' in job and job['read'].get('io_bytes', 0) > 0:
                                bandwidth_kb = job['read'].get('bw', 0)
                                metrics['bandwidth_gb'] = bandwidth_kb / 1024 / 1024
                                metrics['iops'] = job['read'].get('iops', 0)
                                
                                # Latency in microseconds
                                if 'lat_ns' in job['read']:
                                    metrics['latency_us'] = job['read']['lat_ns'].get('mean', 0) / 1000
                                
                                # Percentiles
                                if 'clat_ns' in job['read'] and 'percentile' in job['read']['clat_ns']:
                                    percentiles = {}
                                    p = job['read']['clat_ns']['percentile']
                                    percentiles['p50'] = p.get('50.000000', 0) / 1000
                                    percentiles['p90'] = p.get('90.000000', 0) / 1000
                                    percentiles['p99'] = p.get('99.000000', 0) / 1000
                                    percentiles['mean'] = job['read']['lat_ns'].get('mean', 0) / 1000
                                    metrics['percentiles'] = percentiles
                            
                            # Handle write data if present and read data is not present or this is a write test
                            elif 'write' in job and job['write'].get('io_bytes', 0) > 0:
                                bandwidth_kb = job['write'].get('bw', 0)
                                metrics['bandwidth_gb'] = bandwidth_kb / 1024 / 1024
                                metrics['iops'] = job['write'].get('iops', 0)
                                
                                # Latency in microseconds
                                if 'lat_ns' in job['write']:
                                    metrics['latency_us'] = job['write']['lat_ns'].get('mean', 0) / 1000
                                
                                # Percentiles
                                if 'clat_ns' in job['write'] and 'percentile' in job['write']['clat_ns']:
                                    percentiles = {}
                                    p = job['write']['clat_ns']['percentile']
                                    percentiles['p50'] = p.get('50.000000', 0) / 1000
                                    percentiles['p90'] = p.get('90.000000', 0) / 1000
                                    percentiles['p99'] = p.get('99.000000', 0) / 1000
                                    percentiles['mean'] = job['write']['lat_ns'].get('mean', 0) / 1000
                                    metrics['percentiles'] = percentiles
                            
                            # Store in combined data structure
                            combined_data[test_type][iodepth][numjobs] = metrics
                            
                            operation_type = "read" if job['read'].get('io_bytes', 0) > 0 else "write"
                            print(f"Processed {file_name}: {test_type}, iodepth={iodepth}, numjobs={numjobs}, operation={operation_type}")
                            
                except json.JSONDecodeError:
                    print(f"Error parsing JSON from {file_path}")
                    continue
                
        except Exception as e:
            print(f"Error processing {file_path}: {str(e)}")
            continue
    
    # Write the combined data to the output file
    with open(output_file, 'w') as outfile:
        json.dump(combined_data, outfile, indent=2)
    
    print(f"Combined data written to {output_file}")
    return combined_data

def main():
    # Set up argument parser
    parser = argparse.ArgumentParser(description='Extract and combine FIO benchmark data from multiple files')
    parser.add_argument('directory', help='Directory containing FIO benchmark files')
    parser.add_argument('-o', '--output', default='combined_fio_results.json', 
                        help='Output JSON file (default: combined_fio_results.json)')
    parser.add_argument('-v', '--verbose', action='store_true', 
                        help='Increase output verbosity')
    
    # Parse arguments
    args = parser.parse_args()
    
    # Check if directory exists
    if not os.path.isdir(args.directory):
        print(f"Error: Directory '{args.directory}' does not exist")
        sys.exit(1)
    
    # Extract data
    extract_fio_data(args.directory, args.output)

if __name__ == "__main__":
    main()