import os
import json
import glob
import argparse
import sys
import statistics

def extract_fio_data(directory_path, output_file):
    # Dictionary to store the raw and combined data
    raw_data = {}
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
                        
                        # First step: collect all job data in raw_data
                        for job_index, job in enumerate(data['jobs']):
                            if 'job options' in job and 'rw' in job['job options']:
                                test_type = job['job options']['rw']
                                
                                # Get thread info
                                iodepth = job['job options'].get('iodepth', 'unknown')
                                numjobs = job['job options'].get('numjobs', 'unknown')
                                
                                # Create structure for this test if it doesn't exist
                                if test_type not in raw_data:
                                    raw_data[test_type] = {}
                                    
                                if iodepth not in raw_data[test_type]:
                                    raw_data[test_type][iodepth] = {}
                                
                                if numjobs not in raw_data[test_type][iodepth]:
                                    raw_data[test_type][iodepth][numjobs] = []
                                
                                # Extract performance metrics
                                if 'read' in job and job['read'].get('io_bytes', 0) > 0:
                                    operation = 'read'
                                elif 'write' in job and job['write'].get('io_bytes', 0) > 0:
                                    operation = 'write'
                                else:
                                    continue  # Skip jobs with no I/O
                                
                                # Bandwidth in KB/s
                                bandwidth_kb = job[operation].get('bw', 0)
                                # Convert to GB/s
                                bandwidth_gb = bandwidth_kb / 1024 / 1024
                                
                                # IOPS
                                iops = job[operation].get('iops', 0)
                                
                                # Latency in microseconds
                                lat_ns = 0
                                if 'lat_ns' in job[operation]:
                                    lat_ns = job[operation]['lat_ns'].get('mean', 0)
                                latency_us = lat_ns / 1000
                                
                                # Percentiles
                                percentiles = {}
                                if 'clat_ns' in job[operation] and 'percentile' in job[operation]['clat_ns']:
                                    p = job[operation]['clat_ns']['percentile']
                                    percentiles["p50"] = p.get('50.000000', 0) / 1000
                                    percentiles["p90"] = p.get('90.000000', 0) / 1000
                                    percentiles["p99"] = p.get('99.000000', 0) / 1000
                                    percentiles["mean"] = latency_us
                                
                                # Store this job's metrics
                                job_metrics = {
                                    "file": file_name,
                                    "job_index": job_index,
                                    "bandwidth_gb": bandwidth_gb,
                                    "iops": iops,
                                    "latency_us": latency_us,
                                    "percentiles": percentiles
                                }
                                
                                # Add the job metrics to the raw data
                                raw_data[test_type][iodepth][numjobs].append(job_metrics)
                                
                                print(f"Processed {file_name} job {job_index}: {test_type}, iodepth={iodepth}, numjobs={numjobs}")
                            
                except json.JSONDecodeError:
                    print(f"Error parsing JSON from {file_path}")
                    continue
                
        except Exception as e:
            print(f"Error processing {file_path}: {str(e)}")
            continue
    
    # Now, aggregate the data for the same test parameters
    for test_type in raw_data:
        combined_data[test_type] = {}
        
        for iodepth in raw_data[test_type]:
            combined_data[test_type][iodepth] = {}
            
            for numjobs in raw_data[test_type][iodepth]:
                jobs = raw_data[test_type][iodepth][numjobs]
                
                # For multiple jobs, we need to aggregate
                total_bandwidth = 0
                total_iops = 0
                avg_latency = 0
                p50_values = []
                p90_values = []
                p99_values = []
                
                for job in jobs:
                    total_bandwidth += job["bandwidth_gb"]
                    total_iops += job["iops"]
                    avg_latency += job["latency_us"]
                    
                    if "percentiles" in job:
                        p = job["percentiles"]
                        if "p50" in p:
                            p50_values.append(p["p50"])
                        if "p90" in p:
                            p90_values.append(p["p90"])
                        if "p99" in p:
                            p99_values.append(p["p99"])
                
                # Calculate averages for latency and percentiles
                if len(jobs) > 0:
                    avg_latency /= len(jobs)
                
                # Create the aggregated entry
                aggregated = {
                    "bandwidth_gb": total_bandwidth,
                    "iops": total_iops,
                    "latency_us": avg_latency,
                    "percentiles": {
                        "p50": statistics.mean(p50_values) if p50_values else 0,
                        "p90": statistics.mean(p90_values) if p90_values else 0,
                        "p99": statistics.mean(p99_values) if p99_values else 0,
                        "mean": avg_latency
                    }
                }
                
                # Store the aggregated data
                combined_data[test_type][iodepth][numjobs] = aggregated
    
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
    parser.add_argument('-c', '--csv', action='store_true',
                        help='Generate CSV summary in addition to JSON output')
    
    # Parse arguments
    args = parser.parse_args()
    
    # Check if directory exists
    if not os.path.isdir(args.directory):
        print(f"Error: Directory '{args.directory}' does not exist")
        sys.exit(1)
    
    # Extract data
    combined_data = extract_fio_data(args.directory, args.output)
    
    # Generate CSV if requested
    if args.csv and combined_data:
        csv_file = os.path.splitext(args.output)[0] + '.csv'
        with open(csv_file, 'w') as f:
            # Write header
            f.write("test_type,iodepth,numjobs,bandwidth_gb,iops,latency_us,p50_us,p90_us,p99_us\n")
            
            # Write data rows
            for test_type in combined_data:
                for iodepth in combined_data[test_type]:
                    for numjobs in combined_data[test_type][iodepth]:
                        result = combined_data[test_type][iodepth][numjobs]
                        percentiles = result.get('percentiles', {})
                        
                        row = [
                            test_type,
                            iodepth,
                            numjobs,
                            str(result.get('bandwidth_gb', 0)),
                            str(result.get('iops', 0)),
                            str(result.get('latency_us', 0)),
                            str(percentiles.get('p50', 0)),
                            str(percentiles.get('p90', 0)),
                            str(percentiles.get('p99', 0))
                        ]
                        f.write(','.join(row) + '\n')
        
        print(f"CSV summary written to {csv_file}")

if __name__ == "__main__":
    main()