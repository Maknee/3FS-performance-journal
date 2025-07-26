#!/usr/bin/env python3
"""
KUTrace Logging Benchmark Runner and Plotter

This script runs the KUTrace logging benchmark with various configurations
and generates performance plots for analysis.
"""

import os
import sys
import subprocess
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import argparse
import json
import time
from pathlib import Path
from itertools import product
import numpy as np

class BenchmarkRunner:
    def __init__(self, benchmark_binary, output_dir="benchmark_results", verbose=False):
        self.benchmark_binary = benchmark_binary
        self.output_dir = Path(output_dir)
        self.verbose = verbose
        self.results = []
        
        # Create output directory
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Set up plotting style
        plt.style.use('seaborn-v0_8' if 'seaborn-v0_8' in plt.style.available else 'default')
        sns.set_palette("husl")
    
    def run_benchmark(self, threads, operations, message_size, logger_type="both", mode="both"):
        """Run a single benchmark configuration"""
        
        # Create unique subdirectory for this run
        run_name = f"t{threads}_n{operations}_s{message_size}_{logger_type}_{mode}"
        run_dir = self.output_dir / run_name
        run_dir.mkdir(parents=True, exist_ok=True)
        
        if self.verbose:
            print(f"Running benchmark: {run_name}")
        
        cmd = [
            str(self.benchmark_binary),
            "-t", str(threads),
            "-n", str(operations),
            "-s", str(message_size),
            "-l", logger_type,
            "-m", mode,
            "-d", str(run_dir),
            "-w", "10000",  # Warmup operations
            "-r", "1"       # Single run for speed
        ]
        
        if self.verbose:
            cmd.append("-v")
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if result.returncode != 0:
                print(f"Error running benchmark {run_name} | {' '.join(cmd)} | {result.stderr}")
                return None
            
            # Parse results
            results = self._parse_results(run_dir, threads, operations, message_size, logger_type, mode)
            if results:
                self.results.extend(results)
            
            return results
            
        except subprocess.TimeoutExpired:
            print(f"Benchmark {run_name} timed out after 5 minutes")
            return None
        except Exception as e:
            print(f"Error running benchmark {run_name}: {e}")
            return None
    
    def _parse_results(self, run_dir, threads, operations, message_size, logger_type, mode):
        """Parse CSV results from benchmark run"""
        results = []
        
        # Look for CSV files
        csv_files = list(run_dir.glob("*_results.csv"))
        
        for csv_file in csv_files:
            try:
                df = pd.read_csv(csv_file)
                for _, row in df.iterrows():
                    result = {
                        'threads': threads,
                        'operations': operations,
                        'message_size': message_size,
                        'logger_type': logger_type,
                        'mode': mode,
                        'logger_name': row['Logger'],
                        'mode_name': row['Mode'],
                        'duration_s': row['Duration(s)'],
                        'ops_per_sec': row['OpsPerSec'],
                        'avg_latency_us': row.get('AvgLatency(us)', 0),
                        'min_latency_us': row.get('MinLatency(us)', 0),
                        'max_latency_us': row.get('MaxLatency(us)', 0),
                        'p50_latency_us': row.get('P50(us)', 0),
                        'p95_latency_us': row.get('P95(us)', 0),
                        'p99_latency_us': row.get('P99(us)', 0),
                    }
                    results.append(result)
            except Exception as e:
                if self.verbose:
                    print(f"Error parsing {csv_file}: {e}")
        
        return results
    
    def run_parameter_sweep(self, thread_counts, operation_counts, message_sizes, 
                           logger_types=["both"], modes=["both"]):
        """Run benchmark across parameter ranges"""
        
        total_runs = len(list(product(thread_counts, operation_counts, message_sizes, logger_types, modes)))
        current_run = 0
        
        print(f"Starting parameter sweep: {total_runs} configurations")
        
        for threads, operations, msg_size, logger_type, mode in product(
            thread_counts, operation_counts, message_sizes, logger_types, modes):
            
            current_run += 1
            print(f"[{current_run}/{total_runs}] Running t={threads}, n={operations}, s={msg_size}")
            
            self.run_benchmark(threads, operations, msg_size, logger_type, mode)
            
            # Small delay to prevent overwhelming the system
            time.sleep(0.5)
        
        print(f"Parameter sweep completed. Collected {len(self.results)} result entries.")
    
    def save_results(self, filename="all_results.csv"):
        """Save all results to CSV"""
        if not self.results:
            print("No results to save")
            return
        
        df = pd.DataFrame(self.results)
        output_file = self.output_dir / filename
        df.to_csv(output_file, index=False)
        print(f"Results saved to {output_file}")
        return df
    
    def load_results(self, filename="all_results.csv"):
        """Load results from CSV"""
        input_file = self.output_dir / filename
        if input_file.exists():
            df = pd.read_csv(input_file)
            self.results = df.to_dict('records')
            print(f"Loaded {len(self.results)} results from {input_file}")
            return df
        else:
            print(f"Results file {input_file} not found")
            return None
    
    def plot_throughput_vs_threads(self, save=True):
        """Plot throughput vs number of threads with improved readability"""
        if not self.results:
            print("No results to plot")
            return
        
        df = pd.DataFrame(self.results)
        
        # Filter for throughput results
        throughput_df = df[df['mode_name'] == 'Throughput'].copy()
        
        if throughput_df.empty:
            print("No throughput results found")
            return
        
        # Set up seaborn style for better visuals
        sns.set_style("whitegrid")
        plt.rcParams['font.size'] = 10
        
        # Get unique values for organizing subplots
        loggers = sorted(throughput_df['logger_name'].unique())
        msg_sizes = sorted(throughput_df['message_size'].unique())
        
        # Create subplots: one row per logger type
        fig, axes = plt.subplots(len(loggers), 1, figsize=(14, 6 * len(loggers)))
        if len(loggers) == 1:
            axes = [axes]
        
        # Color palette for message sizes
        colors = sns.color_palette("husl", len(msg_sizes))
        
        for i, logger in enumerate(loggers):
            ax = axes[i]
            
            # Plot each message size as a separate line
            for j, msg_size in enumerate(msg_sizes):
                subset = throughput_df[(throughput_df['logger_name'] == logger) & 
                                     (throughput_df['message_size'] == msg_size)]
                
                if not subset.empty:
                    subset_sorted = subset.sort_values('threads')
                    threads = subset_sorted['threads']
                    throughput_millions = subset_sorted['ops_per_sec'] / 1e6
                    
                    # Plot line with markers
                    line = ax.plot(threads, throughput_millions, 
                                  marker='o', linewidth=3, markersize=8,
                                  color=colors[j], label=f'{msg_size}B messages',
                                  alpha=0.8)
                    
                    # Add value annotations on each point
                    for x, y in zip(threads, throughput_millions):
                        ax.annotate(f'{y:.1f}M', (x, y), 
                                   textcoords="offset points", xytext=(0,10), 
                                   ha='center', fontsize=9, fontweight='bold',
                                   bbox=dict(boxstyle='round,pad=0.3', facecolor='white', alpha=0.7))
            
            # Customize subplot
            ax.set_xlabel('Number of Threads', fontsize=12, fontweight='bold')
            ax.set_ylabel('Throughput (M ops/sec)', fontsize=12, fontweight='bold')
            ax.set_title(f'{logger} Logger Performance', fontsize=14, fontweight='bold', pad=20)
            ax.legend(loc='upper left', frameon=True, fancybox=True, shadow=True)
            ax.grid(True, alpha=0.7, linestyle='-', linewidth=0.5)
            
            # Set y-axis to start from 0 for better comparison
            ax.set_ylim(bottom=0)
            
            # Add background color alternation for better readability
            ax.set_facecolor('#fafafa')
        
        plt.tight_layout(pad=3.0)
        
        # Add overall title
        fig.suptitle('Logging Throughput vs Thread Count - Detailed Comparison', 
                    fontsize=16, fontweight='bold', y=0.98)
        
        if save:
            plt.savefig(self.output_dir / 'throughput_vs_threads.png', dpi=300, bbox_inches='tight',
                       facecolor='white', edgecolor='none')
            print(f"Improved plot saved: {self.output_dir / 'throughput_vs_threads.png'}")
        
        plt.show()
        
        # Also create a summary comparison plot
        self._plot_throughput_summary(throughput_df, save=save)
    
    def _plot_throughput_summary(self, throughput_df, save=True):
        """Create a summary bar chart showing peak throughput for each configuration"""
        # Calculate peak throughput for each logger/message size combination
        summary_data = []
        for logger in throughput_df['logger_name'].unique():
            for msg_size in throughput_df['message_size'].unique():
                subset = throughput_df[(throughput_df['logger_name'] == logger) & 
                                     (throughput_df['message_size'] == msg_size)]
                if not subset.empty:
                    peak_throughput = subset['ops_per_sec'].max() / 1e6
                    best_thread_count = subset.loc[subset['ops_per_sec'].idxmax(), 'threads']
                    summary_data.append({
                        'logger': logger,
                        'message_size': msg_size,
                        'peak_throughput': peak_throughput,
                        'best_threads': best_thread_count
                    })
        
        summary_df = pd.DataFrame(summary_data)
        
        if summary_df.empty:
            return
        
        # Create summary plot
        fig, ax = plt.subplots(figsize=(12, 8))
        
        # Group by message size and create grouped bar chart
        msg_sizes = sorted(summary_df['message_size'].unique())
        loggers = sorted(summary_df['logger'].unique())
        
        x = np.arange(len(msg_sizes))
        width = 0.35
        
        colors = sns.color_palette("Set2", len(loggers))
        
        for i, logger in enumerate(loggers):
            logger_data = summary_df[summary_df['logger'] == logger]
            heights = []
            thread_counts = []
            
            for msg_size in msg_sizes:
                row = logger_data[logger_data['message_size'] == msg_size]
                if not row.empty:
                    heights.append(row['peak_throughput'].iloc[0])
                    thread_counts.append(int(row['best_threads'].iloc[0]))
                else:
                    heights.append(0)
                    thread_counts.append(0)
            
            bars = ax.bar(x + i * width, heights, width, label=logger, 
                         color=colors[i], alpha=0.8, edgecolor='black', linewidth=1)
            
            # Add value labels on bars
            for j, (bar, height, threads) in enumerate(zip(bars, heights, thread_counts)):
                if height > 0:
                    ax.text(bar.get_x() + bar.get_width()/2., height + 0.1,
                           f'{height:.1f}M\n({threads}t)', 
                           ha='center', va='bottom', fontweight='bold', fontsize=10)
        
        ax.set_xlabel('Message Size (bytes)', fontsize=12, fontweight='bold')
        ax.set_ylabel('Peak Throughput (M ops/sec)', fontsize=12, fontweight='bold')
        ax.set_title('Peak Throughput Comparison by Logger and Message Size', 
                    fontsize=14, fontweight='bold', pad=20)
        ax.set_xticks(x + width/2)
        ax.set_xticklabels([f'{size}B' for size in msg_sizes])
        ax.legend(title='Logger Type', frameon=True, fancybox=True, shadow=True)
        ax.grid(True, alpha=0.3, axis='y')
        ax.set_facecolor('#fafafa')
        
        plt.tight_layout()
        
        if save:
            plt.savefig(self.output_dir / 'throughput_summary.png', dpi=300, bbox_inches='tight',
                       facecolor='white', edgecolor='none')
            print(f"Summary plot saved: {self.output_dir / 'throughput_summary.png'}")
        
        plt.show()
    
    def plot_latency_vs_threads(self, save=True):
        """Plot latency vs number of threads"""
        if not self.results:
            print("No results to plot")
            return
        
        df = pd.DataFrame(self.results)
        
        # Filter for latency results
        latency_df = df[df['mode_name'] == 'Latency'].copy()
        
        if latency_df.empty:
            print("No latency results found")
            return
        
        fig, axes = plt.subplots(2, 2, figsize=(15, 12))
        axes = axes.flatten()
        
        latency_metrics = ['avg_latency_us', 'p50_latency_us', 'p95_latency_us', 'p99_latency_us']
        metric_labels = ['Average Latency', 'P50 Latency', 'P95 Latency', 'P99 Latency']
        
        for i, (metric, label) in enumerate(zip(latency_metrics, metric_labels)):
            ax = axes[i]
            
            for logger in latency_df['logger_name'].unique():
                for msg_size in sorted(latency_df['message_size'].unique()):
                    subset = latency_df[(latency_df['logger_name'] == logger) & 
                                      (latency_df['message_size'] == msg_size)]
                    if not subset.empty:
                        subset_sorted = subset.sort_values('threads')
                        ax.plot(subset_sorted['threads'], subset_sorted[metric], 
                               marker='o', linewidth=2, markersize=6,
                               label=f'{logger} (msg={msg_size}B)')
            
            ax.set_xlabel('Number of Threads')
            ax.set_ylabel('Latency (μs)')
            ax.set_title(label)
            ax.grid(True, alpha=0.3)
            if i == 0:  # Only show legend on first subplot
                ax.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
        
        plt.suptitle('Logging Latency vs Thread Count', fontsize=16, fontweight='bold')
        plt.tight_layout()
        
        if save:
            plt.savefig(self.output_dir / 'latency_vs_threads.png', dpi=300, bbox_inches='tight')
            print(f"Plot saved: {self.output_dir / 'latency_vs_threads.png'}")
        
        plt.show()
    
    def plot_throughput_vs_message_size(self, save=True):
        """Plot throughput vs message size with improved readability"""
        if not self.results:
            print("No results to plot")
            return
        
        df = pd.DataFrame(self.results)
        throughput_df = df[df['mode_name'] == 'Throughput'].copy()
        
        if throughput_df.empty:
            print("No throughput results found")
            return
        
        # Set up seaborn style for better visuals
        sns.set_style("whitegrid")
        plt.rcParams['font.size'] = 10
        
        # Get unique values for organizing subplots
        loggers = sorted(throughput_df['logger_name'].unique())
        thread_counts = sorted(throughput_df['threads'].unique())
        
        # Create subplots: one row per logger type
        fig, axes = plt.subplots(len(loggers), 1, figsize=(14, 6 * len(loggers)))
        if len(loggers) == 1:
            axes = [axes]
        
        # Color palette for thread counts
        colors = sns.color_palette("viridis", len(thread_counts))
        
        for i, logger in enumerate(loggers):
            ax = axes[i]
            
            # Plot each thread count as a separate line
            for j, threads in enumerate(thread_counts):
                subset = throughput_df[(throughput_df['logger_name'] == logger) & 
                                     (throughput_df['threads'] == threads)]
                
                if not subset.empty:
                    subset_sorted = subset.sort_values('message_size')
                    msg_sizes = subset_sorted['message_size']
                    throughput_millions = subset_sorted['ops_per_sec'] / 1e6
                    
                    # Plot line with markers
                    line = ax.plot(msg_sizes, throughput_millions, 
                                  marker='o', linewidth=3, markersize=8,
                                  color=colors[j], label=f'{threads} threads',
                                  alpha=0.8)
                    
                    # Add value annotations on each point
                    for x, y in zip(msg_sizes, throughput_millions):
                        ax.annotate(f'{y:.1f}M', (x, y), 
                                   textcoords="offset points", xytext=(0,10), 
                                   ha='center', fontsize=9, fontweight='bold',
                                   bbox=dict(boxstyle='round,pad=0.3', facecolor='white', alpha=0.7))
            
            # Customize subplot
            ax.set_xlabel('Message Size (bytes)', fontsize=12, fontweight='bold')
            ax.set_ylabel('Throughput (M ops/sec)', fontsize=12, fontweight='bold')
            ax.set_title(f'{logger} Logger Performance vs Message Size', fontsize=14, fontweight='bold', pad=20)
            ax.legend(loc='upper right', frameon=True, fancybox=True, shadow=True)
            ax.grid(True, alpha=0.7, linestyle='-', linewidth=0.5)
            ax.set_xscale('log')
            
            # Set y-axis to start from 0 for better comparison
            ax.set_ylim(bottom=0)
            
            # Add background color alternation for better readability
            ax.set_facecolor('#fafafa')
            
            # Improve x-axis formatting for log scale
            ax.set_xticks(sorted(throughput_df['message_size'].unique()))
            ax.set_xticklabels([f'{int(size)}B' for size in sorted(throughput_df['message_size'].unique())])
        
        plt.tight_layout(pad=3.0)
        
        # Add overall title
        fig.suptitle('Logging Throughput vs Message Size - Detailed Comparison', 
                    fontsize=16, fontweight='bold', y=0.98)
        
        if save:
            plt.savefig(self.output_dir / 'throughput_vs_message_size.png', dpi=300, bbox_inches='tight',
                       facecolor='white', edgecolor='none')
            print(f"Improved plot saved: {self.output_dir / 'throughput_vs_message_size.png'}")
        
        plt.show()
    
    def plot_comparison_heatmap(self, save=True):
        """Create heatmap comparing loggers"""
        if not self.results:
            print("No results to plot")
            return
        
        df = pd.DataFrame(self.results)
        
        # Create comparison for throughput
        throughput_df = df[df['mode_name'] == 'Throughput'].copy()
        
        if throughput_df.empty:
            print("No throughput results found")
            return
        
        # Pivot data for heatmap
        pivot_data = throughput_df.pivot_table(
            values='ops_per_sec',
            index=['threads', 'message_size'],
            columns='logger_name',
            aggfunc='mean'
        )
        
        # Calculate speedup ratio (NanoLog vs Binary)
        if 'NanoLog Logger' in pivot_data.columns and 'Binary Logger' in pivot_data.columns:
            speedup = pivot_data['NanoLog Logger'] / pivot_data['Binary Logger']
            
            plt.figure(figsize=(10, 8))
            
            # Reshape for better visualization
            speedup_matrix = speedup.values.reshape(-1, 1)
            
            sns.heatmap(speedup.to_frame(), annot=True, cmap='RdYlBu_r', center=1.0,
                       fmt='.2f', cbar_kws={'label': 'Speedup Ratio (NanoLog/Binary)'})
            
            plt.title('NanoLog vs Binary Logger Speedup', fontsize=14, fontweight='bold')
            plt.ylabel('Configuration (threads, message_size)')
            plt.xlabel('')
            plt.tight_layout()
            
            if save:
                plt.savefig(self.output_dir / 'speedup_heatmap.png', dpi=300, bbox_inches='tight')
                print(f"Plot saved: {self.output_dir / 'speedup_heatmap.png'}")
            
            plt.show()
    
    def generate_summary_report(self):
        """Generate a summary report"""
        if not self.results:
            print("No results to analyze")
            return
        
        df = pd.DataFrame(self.results)
        
        report = []
        report.append("KUTrace Logging Benchmark Summary Report")
        report.append("=" * 50)
        report.append("")
        
        # Basic statistics
        report.append(f"Total benchmark runs: {len(df)}")
        report.append(f"Thread counts tested: {sorted(df['threads'].unique())}")
        report.append(f"Message sizes tested: {sorted(df['message_size'].unique())} bytes")
        report.append(f"Logger types: {df['logger_name'].unique().tolist()}")
        report.append("")
        
        # Performance summary
        throughput_df = df[df['mode_name'] == 'Throughput']
        latency_df = df[df['mode_name'] == 'Latency']
        
        if not throughput_df.empty:
            report.append("Throughput Summary:")
            for logger in throughput_df['logger_name'].unique():
                logger_data = throughput_df[throughput_df['logger_name'] == logger]
                max_throughput = logger_data['ops_per_sec'].max()
                max_config = logger_data.loc[logger_data['ops_per_sec'].idxmax()]
                report.append(f"  {logger}:")
                report.append(f"    Peak throughput: {max_throughput:,.0f} ops/sec")
                report.append(f"    Best config: {max_config['threads']} threads, {max_config['message_size']} bytes")
            report.append("")
        
        if not latency_df.empty:
            report.append("Latency Summary:")
            for logger in latency_df['logger_name'].unique():
                logger_data = latency_df[latency_df['logger_name'] == logger]
                min_latency = logger_data['avg_latency_us'].min()
                min_config = logger_data.loc[logger_data['avg_latency_us'].idxmin()]
                report.append(f"  {logger}:")
                report.append(f"    Lowest avg latency: {min_latency:.3f} μs")
                report.append(f"    Best config: {min_config['threads']} threads, {min_config['message_size']} bytes")
        
        report_text = "\n".join(report)
        print(report_text)
        
        # Save report
        report_file = self.output_dir / "summary_report.txt"
        with open(report_file, 'w') as f:
            f.write(report_text)
        
        print(f"\nFull report saved to: {report_file}")

    def plot_throughput_dashboard(self, save=True):
        """Create a comprehensive dashboard view of throughput data"""
        if not self.results:
            print("No results to plot")
            return
        
        df = pd.DataFrame(self.results)
        throughput_df = df[df['mode_name'] == 'Throughput'].copy()
        
        if throughput_df.empty:
            print("No throughput results found")
            return
        
        # Set up the dashboard layout
        sns.set_style("whitegrid")
        fig = plt.figure(figsize=(20, 16))
        
        # Create a 3x2 grid for different views
        gs = fig.add_gridspec(3, 2, hspace=0.3, wspace=0.3)
        
        # 1. Peak throughput comparison (top left)
        ax1 = fig.add_subplot(gs[0, 0])
        self._create_peak_throughput_bars(throughput_df, ax1)
        
        # 2. Throughput vs threads (top right)
        ax2 = fig.add_subplot(gs[0, 1])
        self._create_compact_threads_plot(throughput_df, ax2)
        
        # 3. Throughput vs message size (middle left)
        ax3 = fig.add_subplot(gs[1, 0])
        self._create_compact_msgsize_plot(throughput_df, ax3)
        
        # 4. Heatmap of all configurations (middle right)
        ax4 = fig.add_subplot(gs[1, 1])
        self._create_throughput_heatmap(throughput_df, ax4)
        
        # 5. Performance efficiency (bottom span)
        ax5 = fig.add_subplot(gs[2, :])
        self._create_efficiency_plot(throughput_df, ax5)
        
        # Add main title
        fig.suptitle('Logging Performance Dashboard - Comprehensive Overview', 
                    fontsize=20, fontweight='bold', y=0.98)
        
        if save:
            plt.savefig(self.output_dir / 'throughput_dashboard.png', dpi=300, bbox_inches='tight',
                       facecolor='white', edgecolor='none')
            print(f"Dashboard saved: {self.output_dir / 'throughput_dashboard.png'}")
        
        plt.show()
    
    def _create_peak_throughput_bars(self, throughput_df, ax):
        """Create peak throughput comparison bars"""
        # Calculate peak throughput for each logger
        peak_data = []
        for logger in throughput_df['logger_name'].unique():
            logger_data = throughput_df[throughput_df['logger_name'] == logger]
            peak_throughput = logger_data['ops_per_sec'].max() / 1e6
            peak_data.append({'logger': logger, 'peak_throughput': peak_throughput})
        
        peak_df = pd.DataFrame(peak_data)
        colors = sns.color_palette("Set1", len(peak_df))
        
        bars = ax.bar(peak_df['logger'], peak_df['peak_throughput'], color=colors, alpha=0.8)
        
        # Add value labels
        for bar, value in zip(bars, peak_df['peak_throughput']):
            ax.text(bar.get_x() + bar.get_width()/2., bar.get_height() + 0.1,
                   f'{value:.1f}M', ha='center', va='bottom', fontweight='bold')
        
        ax.set_title('Peak Throughput by Logger', fontweight='bold')
        ax.set_ylabel('Peak Throughput (M ops/sec)', fontweight='bold')
        ax.grid(True, alpha=0.3, axis='y')
    
    def _create_compact_threads_plot(self, throughput_df, ax):
        """Create compact threads vs throughput plot"""
        colors = sns.color_palette("tab10", len(throughput_df['logger_name'].unique()))
        
        for i, logger in enumerate(throughput_df['logger_name'].unique()):
            logger_data = throughput_df[throughput_df['logger_name'] == logger]
            # Use the best message size for each logger
            best_msg_size = logger_data.groupby('message_size')['ops_per_sec'].max().idxmax()
            subset = logger_data[logger_data['message_size'] == best_msg_size]
            subset_sorted = subset.sort_values('threads')
            
            ax.plot(subset_sorted['threads'], subset_sorted['ops_per_sec'] / 1e6,
                   marker='o', linewidth=2, markersize=6, color=colors[i],
                   label=f'{logger} ({best_msg_size}B)')
        
        ax.set_title('Throughput vs Threads (Best Message Size)', fontweight='bold')
        ax.set_xlabel('Threads', fontweight='bold')
        ax.set_ylabel('Throughput (M ops/sec)', fontweight='bold')
        ax.legend(fontsize=9)
        ax.grid(True, alpha=0.3)
    
    def _create_compact_msgsize_plot(self, throughput_df, ax):
        """Create compact message size vs throughput plot"""
        colors = sns.color_palette("tab10", len(throughput_df['logger_name'].unique()))
        
        for i, logger in enumerate(throughput_df['logger_name'].unique()):
            logger_data = throughput_df[throughput_df['logger_name'] == logger]
            # Use the best thread count for each logger
            best_threads = logger_data.groupby('threads')['ops_per_sec'].max().idxmax()
            subset = logger_data[logger_data['threads'] == best_threads]
            subset_sorted = subset.sort_values('message_size')
            
            ax.plot(subset_sorted['message_size'], subset_sorted['ops_per_sec'] / 1e6,
                   marker='o', linewidth=2, markersize=6, color=colors[i],
                   label=f'{logger} ({best_threads}t)')
        
        ax.set_title('Throughput vs Message Size (Best Thread Count)', fontweight='bold')
        ax.set_xlabel('Message Size (bytes)', fontweight='bold')
        ax.set_ylabel('Throughput (M ops/sec)', fontweight='bold')
        ax.set_xscale('log')
        ax.legend(fontsize=9)
        ax.grid(True, alpha=0.3)
    
    def _create_throughput_heatmap(self, throughput_df, ax):
        """Create heatmap of throughput across all configurations"""
        # Pivot data for heatmap
        heatmap_data = throughput_df.pivot_table(
            values='ops_per_sec', 
            index=['logger_name', 'message_size'], 
            columns='threads', 
            aggfunc='max'
        )
        
        # Convert to millions for readability
        heatmap_data = heatmap_data / 1e6
        
        sns.heatmap(heatmap_data, annot=True, fmt='.1f', cmap='YlOrRd', 
                   ax=ax, cbar_kws={'label': 'Throughput (M ops/sec)'})
        ax.set_title('Throughput Heatmap (All Configurations)', fontweight='bold')
        ax.set_xlabel('Thread Count', fontweight='bold')
        ax.set_ylabel('Logger & Message Size', fontweight='bold')
    
    def _create_efficiency_plot(self, throughput_df, ax):
        """Create throughput per thread efficiency plot"""
        efficiency_data = []
        
        for _, row in throughput_df.iterrows():
            efficiency = (row['ops_per_sec'] / 1e6) / row['threads']
            efficiency_data.append({
                'logger': row['logger_name'],
                'threads': row['threads'],
                'message_size': row['message_size'],
                'efficiency': efficiency
            })
        
        efficiency_df = pd.DataFrame(efficiency_data)
        
        # Plot efficiency vs threads for each logger
        colors = sns.color_palette("tab10", len(efficiency_df['logger'].unique()))
        
        for i, logger in enumerate(efficiency_df['logger'].unique()):
            logger_data = efficiency_df[efficiency_df['logger'] == logger]
            # Average across message sizes
            avg_efficiency = logger_data.groupby('threads')['efficiency'].mean().reset_index()
            
            ax.plot(avg_efficiency['threads'], avg_efficiency['efficiency'],
                   marker='o', linewidth=2, markersize=6, color=colors[i],
                   label=f'{logger}')
        
        ax.set_title('Throughput Efficiency (M ops/sec per thread)', fontweight='bold')
        ax.set_xlabel('Thread Count', fontweight='bold')
        ax.set_ylabel('Efficiency (M ops/sec/thread)', fontweight='bold')
        ax.legend()
        ax.grid(True, alpha=0.3)

def main():
    parser = argparse.ArgumentParser(description='KUTrace Logging Benchmark Runner')
    parser.add_argument('--binary', '-b', required=True, help='Path to benchmark binary')
    parser.add_argument('--output', '-o', default='benchmark_results', help='Output directory')
    parser.add_argument('--threads', '-t', nargs='+', type=int, default=[1, 2, 4, 8], 
                       help='Thread counts to test')
    parser.add_argument('--operations', '-n', nargs='+', type=int, default=[100000, 500000, 1000000],
                       help='Operation counts to test')
    parser.add_argument('--message-sizes', '-s', nargs='+', type=int, default=[64, 256, 1024, 4096],
                       help='Message sizes to test')
    parser.add_argument('--loggers', '-l', nargs='+', default=['both'], 
                       choices=['binary', 'nanolog', 'both'],
                       help='Logger types to test')
    parser.add_argument('--modes', '-m', nargs='+', default=['both'],
                       choices=['latency', 'throughput', 'both'],
                       help='Benchmark modes to test')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    parser.add_argument('--plot-only', action='store_true', help='Only generate plots from existing results')
    
    args = parser.parse_args()
    
    # Check if benchmark binary exists
    if not Path(args.binary).exists():
        print(f"Error: Benchmark binary not found: {args.binary}")
        sys.exit(1)
    
    runner = BenchmarkRunner(args.binary, args.output, args.verbose)
    
    if args.plot_only:
        # Load existing results and plot
        df = runner.load_results()
        if df is None:
            print("No existing results found. Run benchmarks first.")
            sys.exit(1)
    else:
        # Run benchmarks
        print("Starting benchmark parameter sweep...")
        runner.run_parameter_sweep(
            thread_counts=args.threads,
            operation_counts=args.operations,
            message_sizes=args.message_sizes,
            logger_types=args.loggers,
            modes=args.modes
        )
        
        # Save results
        runner.save_results()
    
    # Generate plots
    print("\nGenerating plots...")
    runner.plot_throughput_vs_threads()
    runner.plot_latency_vs_threads()
    runner.plot_throughput_vs_message_size()
    runner.plot_comparison_heatmap()
    
    # Generate summary report
    print("\nGenerating summary report...")
    runner.generate_summary_report()
    
    print(f"\nAll results and plots saved to: {runner.output_dir}")

if __name__ == "__main__":
    main() 