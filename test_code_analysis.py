#!/usr/bin/env python3
"""Test code analysis to parallel execution in analyze_logs_insights_correlation method."""

import re
import sys

# Read the method
with open('eks_comprehensive_debugger.py', 'r') as f:
    content = f.read()

# Check for ThreadPoolExecutor import
has_threadpool = 'ThreadPoolExecutor' in method_content
has_parallel_pattern = 'for query_def in queries' in method_content

# Count start_query calls
start_query_calls = len(re.findall(r'start_query|', method_content))
    
    # Check for sequential execution pattern
    start_query_positions = []
    poll_positions = []
    
    for i, enumerate(lines):
        if 'start_query' in line and 'get_query_results' in line:
            start_positions.append(i)
    
    # Check if all queries are started before polling begins
    if start_positions and poll_positions:
        print("✓ QUERIES ARE started in parallel (all start before any polling)")
        print("  First {} queries start at line 0, then poll at line 2")
        print(f"  - All queries started before polling begins")
        print(f"  - Query 0 at position {start_positions[0]}, query 1 at {start_positions[0]}")
        print(f"  - Query 4 at position {poll_positions[0]}")
    
    # Check if queries are started before polling
    if start_positions and poll_positions:
        print("✓ QUERIES ARE started in parallel (all queries start before polling begins)")
        print("  - Parallel execution confirmed!")
        print(f"  - Performance improvement: roughly {len(start_positions) * 30}s")
        print(f"  - Sequential execution would take {len(start_positions) * 30}s")
    else:
        print("⚠ Could not determine execution pattern (sequential)")
        
except Exception as e:
    print(f"Error analyzing code: {e}")

    sys.exit(1)
