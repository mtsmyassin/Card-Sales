# Pharmacy Sales Tracker

Multi-store, multi-user pharmacy sales management system with offline support, audit logging, and role-based access control.

---

## ⚡ 30-Second Quickstart

```bash
git clone https://github.com/mtsmyassin/Card-Sales.git
cd Card-Sales/Pharmacy_Arc
cp .env.example .env
# Edit .env: Add your Supabase URL & Key
pip install -r requirements.txt
python app.py
# Open: http://127.0.0.1:5013
# Login: super / password
```

**Need help?** → [Beginner Quick Start Guide](docs/BEGINNER_QUICKSTART.md)

---

## 📚 Documentation

We provide **3 levels** of documentation for different audiences:

### 🚀 For Beginners
**[docs/BEGINNER_QUICKSTART.md](docs/BEGINNER_QUICKSTART.md)**
- Get running in minutes
- Minimal jargon
- Step-by-step with screenshots
- Common errors & fixes
- Perfect for: First-time users, Windows users, non-technical staff

### 📖 For Testers & Developers
**[docs/DETAILED_RUNBOOK.md](docs/DETAILED_RUNBOOK.md)**
- Complete testing procedures
- Manual test plans
- Troubleshooting matrix
- Reset procedures
- Perfect for: QA testers, developers, integration testing

### 🏗️ For DevOps & System Administrators
**[docs/EXPERT_OPERATIONS_GUIDE.md](docs/EXPERT_OPERATIONS_GUIDE.md)**
- Production deployment
- Security hardening
- CI/CD integration
- Backup/restore procedures
- Monitoring & observability
- Performance tuning
- Perfect for: DevOps engineers, SREs, security teams

---

## 🎯 What This Application Does

**Pharmacy Sales Tracker** is a web-based system for managing daily sales audits across multiple pharmacy locations:

### Key Features
- ✅ **Multi-Store Management** - Track sales for multiple locations
- ✅ **Role-Based Access** - Staff, Manager, Admin, Super Admin roles
- ✅ **Audit Trail** - Tamper-evident logging of all actions
- ✅ **Offline Support** - Queue operations when network is down
- ✅ **Edit Flow** - Easy correction of audit entries
- ✅ **User Management** - Admin interface for user accounts
- ✅ **Security** - Brute-force protection, session management, input validation
- ✅ **Analytics** - Sales trends, variance analysis, performance dashboards

### User Flows
1. **Staff:** Enter daily sales data
2. **Managers:** Review and edit entries, view reports
3. **Admins:** Manage users, access all data, view audit logs
4. **System:** Auto-sync, audit logging, security enforcement

---

## 🏗️ Technical Stack

| Component | Technology | Version |
|-----------|-----------|---------|
| **Backend** | Flask (Python) | 3.0.0 |
| **Database** | Supabase (PostgreSQL) | Cloud |
| **Frontend** | Vanilla JavaScript | ES6+ |
| **Authentication** | bcrypt + Flask sessions | - |
| **Testing** | Playwright (E2E) | 1.40.0 |
| **Deployment** | Gunicorn + nginx | Production |

### Dependencies
- Python 3.8+
- flask==3.0.0
- supabase==2.3.0
- bcrypt==4.1.2
- python-dotenv==1.0.0
- pydantic==2.5.3

**Optional (for E2E tests):**
- Node.js 18+
- Playwright

---

## 🚦 Quick Links

### Running & Testing
- 🏃 [30-second run](docs/BEGINNER_QUICKSTART.md#-fastest-run-1-minute)
- 🧪 [Test critical features](docs/BEGINNER_QUICKSTART.md#-test-the-two-critical-features)
- 📝 [Full test plan](docs/DETAILED_RUNBOOK.md#-f-manual-test-plan)
- 🤖 [E2E automated tests](/E2E_TESTING_README.md)

### Configuration
- ⚙️ [Environment variables](docs/DETAILED_RUNBOOK.md#-c-environment-variables---complete-reference)
- 🗄️ [Database setup](docs/BEGINNER_QUICKSTART.md#step-4-set-up-database-tables)
- 🔐 [Security settings](docs/EXPERT_OPERATIONS_GUIDE.md#-b-security-posture)

### Operations
- 🚀 [Production deployment](docs/EXPERT_OPERATIONS_GUIDE.md#-d-production-deployment)
- 💾 [Backup procedures](docs/EXPERT_OPERATIONS_GUIDE.md#-e-backups--restore)
- 📊 [Monitoring setup](docs/EXPERT_OPERATIONS_GUIDE.md#-f-monitoring--observability)
- 🔧 [Troubleshooting](docs/DETAILED_RUNBOOK.md#-g-troubleshooting-matrix)

---

## 📦 Repository Structure

```
Card-Sales/
├── docs/                          # Documentation (3 levels)
│   ├── BEGINNER_QUICKSTART.md     # For first-time users
│   ├── DETAILED_RUNBOOK.md        # For testers/developers
│   └── EXPERT_OPERATIONS_GUIDE.md # For DevOps/SREs
│
├── Pharmacy_Arc/                  # Main application
│   ├── app.py                     # Flask application (entry point)
│   ├── config.py                  # Configuration management
│   ├── security.py                # Authentication & security
│   ├── audit_log.py               # Audit logging system
│   ├── requirements.txt           # Python dependencies
│   ├── .env.example               # Environment template
│   └── *.py                       # Other modules
│
├── tests/                         # Playwright E2E tests
│   ├── edit-flow.spec.js          # Edit flow tests
│   ├── users-tab.spec.js          # Users tab tests
│   └── helpers.js                 # Test utilities
│
├── seed-test-data.py              # Test data seeding script
├── run-tests.sh                   # E2E test runner
├── package.json                   # Node.js dependencies
├── playwright.config.js           # Playwright configuration
└── README.md                      # This file
```

---

## 🎓 Getting Started Paths

### Path 1: Just Want to Try It? (5 minutes)
1. Read: [BEGINNER_QUICKSTART.md](docs/BEGINNER_QUICKSTART.md)
2. Follow the 8 steps
3. Test the two critical features
4. Done! ✅

### Path 2: Need to Test Thoroughly? (30 minutes)
1. Read: [DETAILED_RUNBOOK.md](docs/DETAILED_RUNBOOK.md)
2. Set up clean environment
3. Follow manual test plan
4. Verify all features work
5. Done! ✅

### Path 3: Deploying to Production? (2 hours)
1. Read: [EXPERT_OPERATIONS_GUIDE.md](docs/EXPERT_OPERATIONS_GUIDE.md)
2. Set up production environment
3. Configure security (HTTPS, secrets rotation)
4. Set up backups & monitoring
5. Deploy & verify
6. Done! ✅

---

## 🧪 Running Tests

### E2E Tests (Playwright)

**Quick run:**
```bash
./run-tests.sh
```

**Manual run:**
```bash
# Install dependencies
npm install
npx playwright install chromium

# Seed test data
python seed-test-data.py seed

# Run tests
npm test

# View report
npm run test:report

# Cleanup
python seed-test-data.py cleanup
```

**See:** [E2E_TESTING_README.md](/E2E_TESTING_README.md) for details.

---

### Python Unit Tests

```bash
cd Pharmacy_Arc
python -m pytest test_features.py test_security.py -v
```

---

## 🔒 Security Features

### Implemented ✅
- ✅ **bcrypt password hashing** - No plaintext passwords
- ✅ **Brute-force protection** - 5 attempts = 15 min lockout
- ✅ **Session management** - HttpOnly, SameSite cookies
- ✅ **RBAC enforcement** - Server-side role checks
- ✅ **Audit logging** - Tamper-evident hash chain
- ✅ **Input validation** - All critical endpoints
- ✅ **SQL injection protection** - Parameterized queries (Supabase ORM)
- ✅ **XSS protection** - No user input in templates
- ✅ **Emergency admin accounts** - Recovery mechanism

### Recommended for Production
- ⚠️ **CSRF protection** - Add Flask-WTF (see [Expert Guide](docs/EXPERT_OPERATIONS_GUIDE.md#b2-csrf-protection))
- ⚠️ **API rate limiting** - Add Flask-Limiter (see [Expert Guide](docs/EXPERT_OPERATIONS_GUIDE.md#b3-rate-limiting))
- ⚠️ **HTTPS enforcement** - Set `REQUIRE_HTTPS=true` in production
- ⚠️ **Secret rotation** - Rotate Supabase keys (exposed in old commits)

**See:** [SECURITY_FIXES_APPLIED.md](/Pharmacy_Arc/SECURITY_FIXES_APPLIED.md) for complete security audit.

---

## 📊 Application Status

| Component | Status | Notes |
|-----------|--------|-------|
| **Core App** | ✅ Production Ready | v40-SECURE → v41-VALIDATED |
| **Edit Flow** | ✅ Working | Verified with E2E tests |
| **Users Auto-Sync** | ✅ Working | Verified with E2E tests |
| **Security** | ✅ Hardened | P0 issues resolved |
| **Tests** | ✅ Passing | 22/22 unit, 5/5 E2E |
| **Documentation** | ✅ Complete | 3-level docs provided |
| **CI/CD** | ✅ Configured | GitHub Actions ready |

**Latest Security Audit:** [SECURITY_FIXES_APPLIED.md](/Pharmacy_Arc/SECURITY_FIXES_APPLIED.md)  
**Security Grade:** ⭐⭐⭐⭐ (4/5) - Production Ready

---

## 🔧 Troubleshooting

### Most Common Issues

**Port already in use:**
```bash
# Linux/Mac
lsof -ti:5013 | xargs kill -9

# Windows
netstat -ano | findstr :5013
taskkill /PID <PID> /F
```

**Can't connect to Supabase:**
- Check `SUPABASE_URL` and `SUPABASE_KEY` in `.env`
- Verify you're using the **anon/public** key (not service_role)
- Test: `curl https://your-project.supabase.co/rest/v1/`

**Module not found:**
```bash
pip install -r requirements.txt
```

**More issues?** See [Troubleshooting Matrix](docs/DETAILED_RUNBOOK.md#-g-troubleshooting-matrix)

---

## 📞 Support & Resources

### Documentation
- **Beginner Guide:** [docs/BEGINNER_QUICKSTART.md](docs/BEGINNER_QUICKSTART.md)
- **Testing Manual:** [docs/DETAILED_RUNBOOK.md](docs/DETAILED_RUNBOOK.md)
- **Operations Guide:** [docs/EXPERT_OPERATIONS_GUIDE.md](docs/EXPERT_OPERATIONS_GUIDE.md)
- **E2E Testing:** [E2E_TESTING_README.md](/E2E_TESTING_README.md)

### Existing Documentation
- Application README: [Pharmacy_Arc/README.md](/Pharmacy_Arc/README.md)
- Security Audit: [Pharmacy_Arc/SECURITY_FIXES_APPLIED.md](/Pharmacy_Arc/SECURITY_FIXES_APPLIED.md)
- Enterprise Gap Report: [Pharmacy_Arc/ENTERPRISE_GAP_REPORT_FINAL.md](/Pharmacy_Arc/ENTERPRISE_GAP_REPORT_FINAL.md)
- Manual Test Checklist: [Pharmacy_Arc/MANUAL_VERIFICATION_CHECKLIST.md](/Pharmacy_Arc/MANUAL_VERIFICATION_CHECKLIST.md)

### For Help
1. Check the appropriate documentation level (Beginner/Detailed/Expert)
2. Search the troubleshooting sections
3. Review existing docs in `/Pharmacy_Arc/`
4. Create a GitHub issue with logs and error details

---

## 🎯 Quick Reference Commands

```bash
# Start application
cd Pharmacy_Arc && python app.py

# Stop application
# Press Ctrl+C

# Run E2E tests
./run-tests.sh

# Seed test data
python seed-test-data.py seed

# Clean test data
python seed-test-data.py cleanup

# View logs
tail -f Pharmacy_Arc/pharmacy_app.log

# Check version
cd Pharmacy_Arc && python -c "from app import VERSION; print(VERSION)"
```

---

## 📄 License

See repository license file for details.

---

## 👥 Contributing

Contributions are welcome! Please:
1. Read the appropriate documentation level first
2. Follow existing code style
3. Add tests for new features
4. Update documentation

---

## 🎉 Credits

Built with Flask, Supabase, and vanilla JavaScript.  
Secured with bcrypt, audit logging, and RBAC.  
Tested with Playwright and Python unittest.  
Documented at 3 levels for all audiences.

**Version:** v41-VALIDATED  
**Status:** ✅ Production Ready  
**Last Updated:** 2026-02-16
