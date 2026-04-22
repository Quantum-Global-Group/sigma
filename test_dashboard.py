#!/usr/bin/env python3
"""
RazorBill Simple Test Dashboard
Minimal dashboard to test basic functionality
"""

import streamlit as st
import asyncio
from datetime import datetime

# Page config
st.set_page_config(
    page_title="RazorBill Test Dashboard",
    page_icon="📈",
    layout="wide"
)

# Simple test function
async def test_database():
    try:
        from razor_bill.db import SessionLocal
        from sqlalchemy import text
        
        async with SessionLocal() as session:
            # Test basic query
            result = await session.execute(text("SELECT COUNT(*) as count FROM candles"))
            count = result.scalar()
            return f"✅ Database connected! Found {count} candles"
    except Exception as e:
        return f"❌ Database error: {e}"

def main():
    st.title("📈 RazorBill Test Dashboard")
    
    # Test database connection
    st.header("Database Test")
    if st.button("Test Database Connection"):
        with st.spinner("Testing database..."):
            result = asyncio.run(test_database())
            st.write(result)
    
    # Basic info
    st.header("System Info")
    st.write(f"Current time: {datetime.now()}")
    st.write("Dashboard is working!")
    
    # Simple counter
    if 'counter' not in st.session_state:
        st.session_state.counter = 0
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Increment"):
            st.session_state.counter += 1
    with col2:
        if st.button("Reset"):
            st.session_state.counter = 0
    
    st.write(f"Counter: {st.session_state.counter}")

if __name__ == "__main__":
    main()
