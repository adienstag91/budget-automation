"""
Budget Automation Dashboard

A Streamlit web interface for visualizing and analyzing your budget data.
"""
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import calendar
import re

from budget_automation.utils.db_connection import get_db_connection
from budget_automation.review_queue import render_review_queue


def normalize_search_text(text):
    """Normalize text for fuzzy searching - handle HTML entities, remove special chars"""
    if pd.isna(text):
        return ""
    
    text = str(text)
    
    # Decode HTML entities (&amp; → &, &lt; → <, etc.)
    import html
    text = html.unescape(text)
    
    # Replace & with space (so "STOP & SHOP" becomes "STOP SHOP")
    text = text.replace('&', ' ')
    
    # Remove all other special characters
    text = re.sub(r'[^a-zA-Z0-9\s]', ' ', text)
    
    # Collapse multiple spaces
    text = re.sub(r'\s+', ' ', text)
    
    return text.lower().strip()


# Page config
st.set_page_config(
    page_title="Budget Dashboard",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: bold;
        color: #1f77b4;
        margin-bottom: 1rem;
    }
    .metric-card {
        background-color: #f0f2f6;
        padding: 1rem;
        border-radius: 0.5rem;
        border-left: 4px solid #1f77b4;
    }
    .stTabs [data-baseweb="tab-list"] {
        gap: 2rem;
    }
</style>
""", unsafe_allow_html=True)


@st.cache_data(ttl=300)  # Cache for 5 minutes
def load_transactions(start_date=None, end_date=None):
    """Load transactions from database"""
    conn = get_db_connection()
    
    query = """
        SELECT 
            txn_id,
            txn_date,
            post_date,
            merchant_norm,
            merchant_detail,
            description_raw,
            amount,
            direction,
            category,
            subcategory,
            tag_source,
            tag_confidence,
            needs_review,
            notes
        FROM transactions
        WHERE 1=1
    """
    
    params = []
    if start_date:
        query += " AND txn_date >= %s"
        params.append(start_date)
    if end_date:
        query += " AND txn_date <= %s"
        params.append(end_date)
    
    query += " ORDER BY txn_date DESC"
    
    df = pd.read_sql(query, conn, params=params)
    conn.close()
    
    # Convert dates
    df['txn_date'] = pd.to_datetime(df['txn_date'])
    df['post_date'] = pd.to_datetime(df['post_date'])
    
    # Add month/year columns
    df['month'] = df['txn_date'].dt.month
    df['year'] = df['txn_date'].dt.year
    df['month_name'] = df['txn_date'].dt.strftime('%B')
    df['year_month'] = df['txn_date'].dt.strftime('%Y-%m')
    
    # Convert direction to income/expense
    df['type'] = df['direction'].apply(lambda x: 'Income' if x == 'credit' else 'Expense')
    
    # For expenses, make amount negative for easier analysis
    df['signed_amount'] = df.apply(
        lambda row: row['amount'] if row['direction'] == 'credit' else -row['amount'],
        axis=1
    )
    
    return df


@st.cache_data(ttl=300)
def get_summary_stats(df):
    """Calculate summary statistics"""
    expenses = df[df['direction'] == 'debit']['amount'].sum()
    income = df[df['direction'] == 'credit']['amount'].sum()
    net = income - expenses
    
    # Categorization stats
    total = len(df)
    categorized = len(df[~df['needs_review']])
    needs_review = len(df[df['needs_review']])
    
    # Top categories
    top_categories = df[df['direction'] == 'debit'].groupby('category')['amount'].sum().sort_values(ascending=False)
    
    return {
        'expenses': expenses,
        'income': income,
        'net': net,
        'total_transactions': total,
        'categorized': categorized,
        'needs_review': needs_review,
        'top_categories': top_categories
    }


def render_overview(df, stats):
    """Render overview dashboard"""
    st.markdown('<p class="main-header">💰 Budget Overview</p>', unsafe_allow_html=True)
    
    # Key metrics - financial only
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric(
            "Total Expenses",
            f"${stats['expenses']:,.2f}",
            delta=None,
            delta_color="inverse"
        )
    
    with col2:
        st.metric(
            "Total Income",
            f"${stats['income']:,.2f}",
            delta=None
        )
    
    with col3:
        st.metric(
            "Net",
            f"${stats['net']:,.2f}",
            delta=None,
            delta_color="normal" if stats['net'] >= 0 else "inverse"
        )
    
    st.divider()
    
    # Charts row
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("📊 Spending by Category")
        
        # Pie chart
        category_totals = df[df['direction'] == 'debit'].groupby('category')['amount'].sum().reset_index()
        category_totals = category_totals.sort_values('amount', ascending=False).head(10)
        
        fig = px.pie(
            category_totals,
            values='amount',
            names='category',
            title='Top 10 Categories',
            hole=0.4
        )
        fig.update_traces(textposition='inside', textinfo='percent+label')
        st.plotly_chart(fig, use_container_width=True)
    
    with col2:
        st.subheader("📈 Top Categories")
        
        # Bar chart
        fig = px.bar(
            category_totals,
            x='amount',
            y='category',
            orientation='h',
            title='Spending by Category',
            labels={'amount': 'Total ($)', 'category': 'Category'}
        )
        fig.update_layout(showlegend=False, yaxis={'categoryorder':'total ascending'})
        st.plotly_chart(fig, use_container_width=True)
    
    # Monthly trend
    st.subheader("📅 Monthly Spending Trend")
    
    monthly = df[df['direction'] == 'debit'].groupby('year_month')['amount'].sum().reset_index()
    monthly = monthly.sort_values('year_month')
    
    fig = px.line(
        monthly,
        x='year_month',
        y='amount',
        title='Monthly Expenses Over Time',
        labels={'year_month': 'Month', 'amount': 'Total Expenses ($)'},
        markers=True
    )
    fig.update_layout(hovermode='x unified')
    st.plotly_chart(fig, use_container_width=True)


def render_transactions(df):
    """Render transaction list with filters"""
    st.markdown('<p class="main-header">📝 Transactions</p>', unsafe_allow_html=True)
    
    # Filters
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        categories = ['All'] + sorted(df['category'].unique().tolist())
        selected_category = st.selectbox('Category', categories, key='txn_category')
    
    with col2:
        types = ['All', 'Expense', 'Income']
        selected_type = st.selectbox('Type', types, key='txn_type')
    
    with col3:
        review_options = ['All', 'Needs Review', 'Categorized']
        selected_review = st.selectbox('Status', review_options, key='txn_status')
    
    with col4:
        search = st.text_input('Search merchant (fuzzy)', '', key='txn_search')
    
    # Apply filters
    filtered_df = df.copy()
    
    if selected_category != 'All':
        filtered_df = filtered_df[filtered_df['category'] == selected_category]
    
    if selected_type == 'Expense':
        filtered_df = filtered_df[filtered_df['direction'] == 'debit']
    elif selected_type == 'Income':
        filtered_df = filtered_df[filtered_df['direction'] == 'credit']
    
    if selected_review == 'Needs Review':
        filtered_df = filtered_df[filtered_df['needs_review'] == True]
    elif selected_review == 'Categorized':
        filtered_df = filtered_df[filtered_df['needs_review'] == False]
    
    if search:
        # Fuzzy search - normalize and check if ALL search words are present
        search_normalized = normalize_search_text(search)
        search_words = search_normalized.split()
        
        filtered_df['merchant_normalized'] = filtered_df['merchant_norm'].apply(normalize_search_text)
        filtered_df['description_normalized'] = filtered_df['description_raw'].apply(normalize_search_text)
        
        # Function to check if all search words are in the text
        def contains_all_words(text, words):
            return all(word in text for word in words)
        
        # Match if all search words are in merchant OR description
        mask = (
            filtered_df['merchant_normalized'].apply(lambda x: contains_all_words(x, search_words)) |
            filtered_df['description_normalized'].apply(lambda x: contains_all_words(x, search_words))
        )
        filtered_df = filtered_df[mask]
    
    # Display count
    st.info(f"Showing {len(filtered_df):,} transactions")
    
    # Format display dataframe
    display_df = filtered_df[[
        'txn_date', 'merchant_norm', 'amount', 'category', 
        'subcategory', 'tag_source', 'needs_review'
    ]].copy()
    
    display_df['txn_date'] = display_df['txn_date'].dt.strftime('%Y-%m-%d')
    display_df['amount'] = display_df['amount'].apply(lambda x: f"${x:,.2f}")
    display_df = display_df.rename(columns={
        'txn_date': 'Date',
        'merchant_norm': 'Merchant',
        'amount': 'Amount',
        'category': 'Category',
        'subcategory': 'Subcategory',
        'tag_source': 'Source',
        'needs_review': 'Needs Review'
    })
    
    # Display table
    st.dataframe(
        display_df,
        use_container_width=True,
        height=600,
        hide_index=True
    )
    
    # Download button
    csv = filtered_df.to_csv(index=False)
    st.download_button(
        label="📥 Download as CSV",
        data=csv,
        file_name=f"transactions_{datetime.now().strftime('%Y%m%d')}.csv",
        mime="text/csv"
    )


def render_category_breakdown(df):
    """Render detailed category breakdown"""
    st.markdown('<p class="main-header">🏷️ Category Breakdown</p>', unsafe_allow_html=True)
    
    # Category selector
    expenses_df = df[df['direction'] == 'debit']
    categories = sorted(expenses_df['category'].unique().tolist())
    
    selected_category = st.selectbox('Select Category', categories, key='cat_selector')
    
    # Filter by category
    category_df = expenses_df[expenses_df['category'] == selected_category]
    
    # Summary
    col1, col2, col3 = st.columns(3)
    
    with col1:
        total = category_df['amount'].sum()
        st.metric("Total Spent", f"${total:,.2f}")
    
    with col2:
        count = len(category_df)
        st.metric("Transactions", f"{count:,}")
    
    with col3:
        avg = category_df['amount'].mean()
        st.metric("Average", f"${avg:,.2f}")
    
    st.divider()
    
    # Subcategory breakdown
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("By Subcategory")
        subcat_totals = category_df.groupby('subcategory')['amount'].sum().reset_index()
        subcat_totals = subcat_totals.sort_values('amount', ascending=False)
        
        fig = px.bar(
            subcat_totals,
            x='subcategory',
            y='amount',
            title=f'{selected_category} - Subcategories',
            labels={'subcategory': 'Subcategory', 'amount': 'Amount ($)'}
        )
        st.plotly_chart(fig, use_container_width=True)
    
    with col2:
        st.subheader("By Merchant")
        merchant_totals = category_df.groupby('merchant_norm')['amount'].sum().reset_index()
        merchant_totals = merchant_totals.sort_values('amount', ascending=False).head(10)
        
        fig = px.bar(
            merchant_totals,
            x='merchant_norm',
            y='amount',
            title=f'Top 10 Merchants in {selected_category}',
            labels={'merchant_norm': 'Merchant', 'amount': 'Amount ($)'}
        )
        fig.update_layout(xaxis_tickangle=-45)
        st.plotly_chart(fig, use_container_width=True)
    
    # Monthly trend for this category
    st.subheader("Monthly Trend")
    monthly_cat = category_df.groupby('year_month')['amount'].sum().reset_index()
    monthly_cat = monthly_cat.sort_values('year_month')
    
    fig = px.line(
        monthly_cat,
        x='year_month',
        y='amount',
        title=f'{selected_category} - Monthly Spending',
        labels={'year_month': 'Month', 'amount': 'Amount ($)'},
        markers=True
    )
    st.plotly_chart(fig, use_container_width=True)


def main():
    """Main dashboard app"""
    
    # Initialize session state for tab persistence
    if 'active_tab' not in st.session_state:
        st.session_state.active_tab = 0
    
    # Sidebar
    with st.sidebar:
        st.title("💰 Budget Dashboard")
        st.divider()
        
        # Date range selector
        st.subheader("📅 Date Range")
        
        date_option = st.radio(
            "Select range:",
            ["All Time", "This Month", "Last Month", "This Year", "Custom"],
            key='date_option'
        )
        
        if date_option == "All Time":
            start_date = None
            end_date = None
        elif date_option == "This Month":
            today = datetime.now()
            start_date = today.replace(day=1)
            end_date = today
        elif date_option == "Last Month":
            today = datetime.now()
            last_month = today.replace(day=1) - timedelta(days=1)
            start_date = last_month.replace(day=1)
            end_date = last_month
        elif date_option == "This Year":
            today = datetime.now()
            start_date = today.replace(month=1, day=1)
            end_date = today
        else:  # Custom
            col1, col2 = st.columns(2)
            with col1:
                start_date = st.date_input("From", value=datetime.now() - timedelta(days=90))
            with col2:
                end_date = st.date_input("To", value=datetime.now())
        
        st.divider()
        
        # Load data for stats display
        try:
            df_for_stats = load_transactions(start_date, end_date)
            if len(df_for_stats) > 0:
                stats = get_summary_stats(df_for_stats)
                
                # System Stats
                st.subheader("📊 System Stats")
                
                categorization_pct = (stats['categorized'] / stats['total_transactions']) * 100
                
                st.metric(
                    "Total Transactions",
                    f"{stats['total_transactions']:,}",
                    delta=None
                )
                
                st.metric(
                    "Auto-Categorized",
                    f"{categorization_pct:.1f}%",
                    delta=f"{stats['categorized']:,} of {stats['total_transactions']:,}"
                )
                
                if stats['needs_review'] > 0:
                    st.metric(
                        "Needs Review",
                        f"{stats['needs_review']:,}",
                        delta=f"{(stats['needs_review']/stats['total_transactions']*100):.1f}%",
                        delta_color="inverse"
                    )
                
                st.divider()
        except:
            pass
        
        # About
        st.subheader("ℹ️ About")
        st.caption("Budget Automation System")
        st.caption("Built with Streamlit + Claude")
        
        if st.button("🔄 Refresh Data"):
            st.cache_data.clear()
            st.rerun()
    
    # Load data
    try:
        with st.spinner("Loading transactions..."):
            df = load_transactions(start_date, end_date)
        
        if len(df) == 0:
            st.warning("No transactions found for the selected date range.")
            return
        
        stats = get_summary_stats(df)
        
        # Main content tabs with session state
        tab_names = ["📊 Overview", "📝 Transactions", "🏷️ Categories", "📋 Review Queue"]
        
        # Create tabs - Streamlit handles the selected index internally
        tabs = st.tabs(tab_names)
        
        with tabs[0]:
            render_overview(df, stats)
        
        with tabs[1]:
            render_transactions(df)
        
        with tabs[2]:
            render_category_breakdown(df)
        
        with tabs[3]:
            render_review_queue()
        
    except Exception as e:
        st.error(f"Error loading data: {e}")
        st.exception(e)


if __name__ == "__main__":
    main()
