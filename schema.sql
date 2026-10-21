-- LeaveFlow PostgreSQL schema (generated from database/models.py)
-- Regenerate with: python -m database.init_db --export-schema

CREATE TABLE approval_rules (
	id SERIAL NOT NULL, 
	min_days INTEGER NOT NULL, 
	stages VARCHAR(100) NOT NULL, 
	description VARCHAR(200), 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_approval_rules_min_days CHECK (min_days >= 0), 
	UNIQUE (min_days)
);

CREATE TABLE departments (
	id SERIAL NOT NULL, 
	name VARCHAR(100) NOT NULL, 
	head_employee_id INTEGER, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (name)
);

CREATE TABLE holidays (
	id SERIAL NOT NULL, 
	holiday_date DATE NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	is_active BOOLEAN DEFAULT true NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (holiday_date)
);

CREATE TABLE leave_types (
	id SERIAL NOT NULL, 
	code VARCHAR(20) NOT NULL, 
	name VARCHAR(80) NOT NULL, 
	description VARCHAR(300), 
	annual_allowance NUMERIC(5, 1) NOT NULL, 
	tracks_balance BOOLEAN DEFAULT true NOT NULL, 
	requires_approval BOOLEAN DEFAULT true NOT NULL, 
	requires_document BOOLEAN DEFAULT false NOT NULL, 
	document_threshold_days INTEGER DEFAULT '0' NOT NULL, 
	document_description VARCHAR(80) DEFAULT 'Supporting documentation' NOT NULL, 
	can_carry_forward BOOLEAN DEFAULT false NOT NULL, 
	carry_forward_limit NUMERIC(5, 1) DEFAULT '0' NOT NULL, 
	max_consecutive_days INTEGER, 
	is_active BOOLEAN DEFAULT true NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_leave_types_allowance CHECK (annual_allowance >= 0), 
	CONSTRAINT ck_leave_types_max_days CHECK (max_consecutive_days IS NULL OR max_consecutive_days > 0), 
	UNIQUE (code), 
	UNIQUE (name)
);

CREATE TABLE roles (
	id SERIAL NOT NULL, 
	name VARCHAR(30) NOT NULL, 
	description VARCHAR(200), 
	PRIMARY KEY (id), 
	UNIQUE (name)
);

CREATE TABLE system_settings (
	key VARCHAR(60) NOT NULL, 
	value VARCHAR(200) NOT NULL, 
	description VARCHAR(200), 
	PRIMARY KEY (key)
);

CREATE TABLE employees (
	id SERIAL NOT NULL, 
	employee_code VARCHAR(20) NOT NULL, 
	first_name VARCHAR(80) NOT NULL, 
	last_name VARCHAR(80) NOT NULL, 
	email VARCHAR(160) NOT NULL, 
	job_title VARCHAR(120), 
	department_id INTEGER NOT NULL, 
	manager_id INTEGER, 
	hire_date DATE NOT NULL, 
	is_active BOOLEAN DEFAULT true NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (employee_code), 
	UNIQUE (email), 
	FOREIGN KEY(department_id) REFERENCES departments (id), 
	FOREIGN KEY(manager_id) REFERENCES employees (id)
);
CREATE INDEX ix_employees_department_id ON employees (department_id);
CREATE INDEX ix_employees_manager_id ON employees (manager_id);

CREATE TABLE leave_balances (
	id SERIAL NOT NULL, 
	employee_id INTEGER NOT NULL, 
	leave_type_id INTEGER NOT NULL, 
	year INTEGER NOT NULL, 
	allocated NUMERIC(6, 1) NOT NULL, 
	carried_forward NUMERIC(6, 1) DEFAULT '0' NOT NULL, 
	used NUMERIC(6, 1) DEFAULT '0' NOT NULL, 
	pending NUMERIC(6, 1) DEFAULT '0' NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_balance_employee_type_year UNIQUE (employee_id, leave_type_id, year), 
	CONSTRAINT ck_balance_non_negative CHECK (used >= 0 AND pending >= 0), 
	FOREIGN KEY(employee_id) REFERENCES employees (id), 
	FOREIGN KEY(leave_type_id) REFERENCES leave_types (id)
);
CREATE INDEX ix_leave_balances_employee_id ON leave_balances (employee_id);

CREATE TABLE leave_requests (
	id SERIAL NOT NULL, 
	employee_id INTEGER NOT NULL, 
	leave_type_id INTEGER NOT NULL, 
	start_date DATE NOT NULL, 
	end_date DATE NOT NULL, 
	working_days INTEGER NOT NULL, 
	reason TEXT, 
	document_name VARCHAR(200), 
	document_content BYTEA, 
	status VARCHAR(30) NOT NULL, 
	submitted_at TIMESTAMP WITH TIME ZONE, 
	decided_at TIMESTAMP WITH TIME ZONE, 
	decision_reason TEXT, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_request_dates CHECK (end_date >= start_date), 
	CONSTRAINT ck_request_days CHECK (working_days >= 0), 
	CONSTRAINT ck_request_status CHECK (status IN ('DRAFT', 'SUBMITTED', 'MANAGER_PENDING', 'HR_PENDING', 'DEPARTMENT_HEAD_PENDING', 'APPROVED', 'REJECTED', 'CANCELLED')), 
	FOREIGN KEY(employee_id) REFERENCES employees (id), 
	FOREIGN KEY(leave_type_id) REFERENCES leave_types (id)
);
CREATE INDEX ix_requests_dates ON leave_requests (start_date, end_date);
CREATE INDEX ix_requests_employee_status ON leave_requests (employee_id, status);

CREATE TABLE users (
	id SERIAL NOT NULL, 
	username VARCHAR(60) NOT NULL, 
	password_hash VARCHAR(255) NOT NULL, 
	role_id INTEGER NOT NULL, 
	employee_id INTEGER NOT NULL, 
	is_active BOOLEAN DEFAULT true NOT NULL, 
	last_login_at TIMESTAMP WITH TIME ZONE, 
	failed_attempts INTEGER DEFAULT '0' NOT NULL, 
	locked_until TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (username), 
	FOREIGN KEY(role_id) REFERENCES roles (id), 
	UNIQUE (employee_id), 
	FOREIGN KEY(employee_id) REFERENCES employees (id)
);

CREATE TABLE approval_steps (
	id SERIAL NOT NULL, 
	request_id INTEGER NOT NULL, 
	step_order INTEGER NOT NULL, 
	stage VARCHAR(30) NOT NULL, 
	approver_employee_id INTEGER, 
	status VARCHAR(20) NOT NULL, 
	activated_at TIMESTAMP WITH TIME ZONE, 
	decided_at TIMESTAMP WITH TIME ZONE, 
	acted_by_user_id INTEGER, 
	comments TEXT, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_step_request_order UNIQUE (request_id, step_order), 
	CONSTRAINT ck_step_stage CHECK (stage IN ('MANAGER', 'HR', 'DEPARTMENT_HEAD')), 
	CONSTRAINT ck_step_status CHECK (status IN ('WAITING', 'PENDING', 'APPROVED', 'REJECTED', 'SKIPPED', 'CANCELLED')), 
	FOREIGN KEY(request_id) REFERENCES leave_requests (id) ON DELETE CASCADE, 
	FOREIGN KEY(approver_employee_id) REFERENCES employees (id), 
	FOREIGN KEY(acted_by_user_id) REFERENCES users (id)
);
CREATE INDEX ix_steps_approver_status ON approval_steps (approver_employee_id, status);

CREATE TABLE audit_logs (
	id SERIAL NOT NULL, 
	user_id INTEGER, 
	action VARCHAR(60) NOT NULL, 
	entity_type VARCHAR(40) NOT NULL, 
	entity_id VARCHAR(40), 
	old_value JSON, 
	new_value JSON, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE SET NULL
);
CREATE INDEX ix_audit_created ON audit_logs (created_at);
CREATE INDEX ix_audit_entity ON audit_logs (entity_type, entity_id);

CREATE TABLE notifications (
	id SERIAL NOT NULL, 
	user_id INTEGER NOT NULL, 
	title VARCHAR(150) NOT NULL, 
	message TEXT NOT NULL, 
	category VARCHAR(40) NOT NULL, 
	request_id INTEGER, 
	is_read BOOLEAN DEFAULT false NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
	FOREIGN KEY(request_id) REFERENCES leave_requests (id) ON DELETE SET NULL
);
CREATE INDEX ix_notifications_user_read ON notifications (user_id, is_read);

ALTER TABLE departments ADD CONSTRAINT fk_departments_head_employee FOREIGN KEY(head_employee_id) REFERENCES employees (id);