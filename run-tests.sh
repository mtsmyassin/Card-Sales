#!/bin/bash
# Quick start script for running E2E tests

set -e

echo "🧪 Pharmacy Sales Tracker E2E Test Runner"
echo "=========================================="
echo ""

# Check if .env exists
if [ ! -f "Pharmacy_Arc/.env" ]; then
    echo "⚠️  .env file not found!"
    echo "📝 To run tests, you need to configure Supabase credentials:"
    echo ""
    echo "1. Copy the example file:"
    echo "   cp Pharmacy_Arc/.env.test Pharmacy_Arc/.env"
    echo ""
    echo "2. Edit Pharmacy_Arc/.env and add your test Supabase credentials:"
    echo "   SUPABASE_URL=https://your-test-project.supabase.co"
    echo "   SUPABASE_KEY=your-test-key"
    echo ""
    echo "3. Run this script again"
    echo ""
    exit 1
fi

# Check if node_modules exists
if [ ! -d "node_modules" ]; then
    echo "📦 Installing npm dependencies..."
    npm install
fi

# Check if Playwright is installed
if [ ! -d "$HOME/.cache/ms-playwright/chromium-"* ]; then
    echo "🎭 Installing Playwright browsers..."
    npx playwright install chromium
fi

# Check if Python dependencies are installed
echo "🐍 Checking Python dependencies..."
cd Pharmacy_Arc
if ! python3 -c "import supabase" 2>/dev/null; then
    echo "📦 Installing Python dependencies..."
    pip install -r requirements.txt
fi
cd ..

# Seed test data
echo ""
echo "🌱 Seeding test data..."
python3 seed-test-data.py seed

# Run tests
echo ""
echo "🧪 Running Playwright tests..."
echo ""

# Check for command line argument
if [ "$1" == "headed" ]; then
    npm run test:headed
elif [ "$1" == "debug" ]; then
    npm run test:debug
elif [ "$1" == "ui" ]; then
    npm run test:ui
else
    npm test
fi

# Show test report
echo ""
echo "📊 Tests complete!"
echo ""
echo "To view the HTML report, run:"
echo "  npm run test:report"
echo ""
echo "To clean up test data, run:"
echo "  python3 seed-test-data.py cleanup"
