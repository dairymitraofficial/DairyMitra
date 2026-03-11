CREATE database dairymitra;
USE dairymitra;
-- =========================================
-- USERS TABLE
-- =========================================
CREATE TABLE users (
    id INT AUTO_INCREMENT PRIMARY KEY,

    email VARCHAR(255) NOT NULL UNIQUE,
    password VARCHAR(255) NOT NULL,

    phone VARCHAR(20),
    dairy_name VARCHAR(255),

    is_verified BOOLEAN DEFAULT FALSE,

    otp VARCHAR(10),
    otp_expiry DATETIME,

    reset_token VARCHAR(255),
    reset_token_expiry DATETIME,

    otp_code VARCHAR(6),
    otp_created_at DATETIME,

    security_password_hash VARCHAR(255),
    security_otp VARCHAR(6),
    security_otp_expiry DATETIME
);


-- =========================================
-- VENDORS TABLE
-- =========================================
CREATE TABLE vendors (

    id INT AUTO_INCREMENT PRIMARY KEY,

    vendor_id INT NOT NULL,

    name VARCHAR(100) NOT NULL,

    address TEXT,

    milk_type ENUM('cow','buffalo','both') DEFAULT 'cow',

    phone VARCHAR(15),

    user_id INT NOT NULL,

    FOREIGN KEY (user_id)
    REFERENCES users(id)
    ON DELETE CASCADE,

    UNIQUE KEY unique_vendor_per_user (vendor_id,user_id)

);


-- =========================================
-- MILK COLLECTION TABLE
-- =========================================
CREATE TABLE milk_collection (

    id INT AUTO_INCREMENT PRIMARY KEY,

    vendor_id INT,
    user_id INT,

    date DATE,

    slot ENUM('morning','evening') NOT NULL,

    milk_type ENUM('cow','buffalo') NOT NULL,

    quantity FLOAT NOT NULL,

    FOREIGN KEY (vendor_id,user_id)
    REFERENCES vendors(vendor_id,user_id)
    ON DELETE CASCADE,

    UNIQUE KEY unique_entry
    (vendor_id,user_id,date,slot,milk_type)

);


-- =========================================
-- ADVANCE TABLE
-- =========================================
CREATE TABLE advance (

    id INT AUTO_INCREMENT PRIMARY KEY,

    vendor_id INT,
    user_id INT,

    date DATE,

    amount FLOAT NOT NULL,

    FOREIGN KEY (vendor_id,user_id)
    REFERENCES vendors(vendor_id,user_id)
    ON DELETE CASCADE,

    UNIQUE KEY unique_advance
    (vendor_id,user_id,date)

);


-- =========================================
-- FOOD SACK RATE TABLE
-- =========================================
CREATE TABLE food_sack_rates (

    id INT AUTO_INCREMENT PRIMARY KEY,

    user_id INT NOT NULL,

    name VARCHAR(100) NOT NULL,

    rate FLOAT NOT NULL,

    date_from DATE NOT NULL,

    FOREIGN KEY (user_id)
    REFERENCES users(id)
    ON DELETE CASCADE

);


-- =========================================
-- FOOD SACK TABLE
-- =========================================
CREATE TABLE food_sack (

    id INT AUTO_INCREMENT PRIMARY KEY,

    vendor_id INT,
    user_id INT,

    date DATE,

    sack_qty INT NOT NULL,

    sack_rate_id INT NOT NULL,

    total_cost FLOAT NOT NULL,

    FOREIGN KEY (vendor_id,user_id)
    REFERENCES vendors(vendor_id,user_id)
    ON DELETE CASCADE,

    FOREIGN KEY (sack_rate_id)
    REFERENCES food_sack_rates(id)
    ON DELETE CASCADE,

    UNIQUE KEY unique_food
    (vendor_id,user_id,date,sack_rate_id)

);


-- =========================================
-- MILK RATE TABLE
-- =========================================
CREATE TABLE milk_rates (

    id INT AUTO_INCREMENT PRIMARY KEY,

    user_id INT NOT NULL,

    animal ENUM('cow','buffalo') NOT NULL,

    rate FLOAT NOT NULL,

    date_from DATE NOT NULL,

    FOREIGN KEY (user_id)
    REFERENCES users(id)
    ON DELETE CASCADE

);

CREATE INDEX idx_milk_vendor_date
ON milk_collection(vendor_id,user_id,date);

CREATE INDEX idx_advance_vendor_date
ON advance(vendor_id,user_id,date);

CREATE INDEX idx_food_vendor_date
ON food_sack(vendor_id,user_id,date);

CREATE INDEX idx_vendor_user
ON vendors(user_id);

CREATE INDEX idx_rates_user
ON milk_rates(user_id,date_from);




-- =========================================
-- USERS TABLE
-- =========================================
CREATE TABLE users (
    id INT AUTO_INCREMENT PRIMARY KEY,

    email VARCHAR(255) NOT NULL UNIQUE,
    password VARCHAR(255) NOT NULL,

    phone VARCHAR(20),
    dairy_name VARCHAR(255),

    is_verified BOOLEAN DEFAULT FALSE,

    otp VARCHAR(10),
    otp_expiry DATETIME,

    reset_token VARCHAR(255),
    reset_token_expiry DATETIME,

    otp_code VARCHAR(6),
    otp_created_at DATETIME,

    security_password_hash VARCHAR(255),
    security_otp VARCHAR(6),
    security_otp_expiry DATETIME
);


-- =========================================
-- VENDORS TABLE
-- =========================================
CREATE TABLE vendors (

    id INT AUTO_INCREMENT PRIMARY KEY,

    vendor_id INT NOT NULL,

    name VARCHAR(100) NOT NULL,

    address TEXT,

    milk_type ENUM('cow','buffalo','both') DEFAULT 'cow',

    phone VARCHAR(15),

    user_id INT NOT NULL,

    FOREIGN KEY (user_id)
    REFERENCES users(id)
    ON DELETE CASCADE,

    UNIQUE KEY unique_vendor_per_user (vendor_id,user_id)

);


-- =========================================
-- MILK COLLECTION TABLE
-- =========================================
CREATE TABLE milk_collection (

    id INT AUTO_INCREMENT PRIMARY KEY,

    vendor_id INT,
    user_id INT,

    date DATE,

    slot ENUM('morning','evening') NOT NULL,

    milk_type ENUM('cow','buffalo') NOT NULL,

    quantity FLOAT NOT NULL,

    FOREIGN KEY (vendor_id,user_id)
    REFERENCES vendors(vendor_id,user_id)
    ON DELETE CASCADE,

    UNIQUE KEY unique_entry
    (vendor_id,user_id,date,slot,milk_type)

);


-- =========================================
-- ADVANCE TABLE
-- =========================================
CREATE TABLE advance (

    id INT AUTO_INCREMENT PRIMARY KEY,

    vendor_id INT,
    user_id INT,

    date DATE,

    amount FLOAT NOT NULL,

    FOREIGN KEY (vendor_id,user_id)
    REFERENCES vendors(vendor_id,user_id)
    ON DELETE CASCADE,

    UNIQUE KEY unique_advance
    (vendor_id,user_id,date)

);


-- =========================================
-- FOOD SACK RATE TABLE
-- =========================================
CREATE TABLE food_sack_rates (

    id INT AUTO_INCREMENT PRIMARY KEY,

    user_id INT NOT NULL,

    name VARCHAR(100) NOT NULL,

    rate FLOAT NOT NULL,

    date_from DATE NOT NULL,

    FOREIGN KEY (user_id)
    REFERENCES users(id)
    ON DELETE CASCADE

);


-- =========================================
-- FOOD SACK TABLE
-- =========================================
CREATE TABLE food_sack (

    id INT AUTO_INCREMENT PRIMARY KEY,

    vendor_id INT,
    user_id INT,

    date DATE,

    sack_qty INT NOT NULL,

    sack_rate_id INT NOT NULL,

    total_cost FLOAT NOT NULL,

    FOREIGN KEY (vendor_id,user_id)
    REFERENCES vendors(vendor_id,user_id)
    ON DELETE CASCADE,

    FOREIGN KEY (sack_rate_id)
    REFERENCES food_sack_rates(id)
    ON DELETE CASCADE,

    UNIQUE KEY unique_food
    (vendor_id,user_id,date,sack_rate_id)

);


-- =========================================
-- MILK RATE TABLE
-- =========================================
CREATE TABLE milk_rates (

    id INT AUTO_INCREMENT PRIMARY KEY,

    user_id INT NOT NULL,

    animal ENUM('cow','buffalo') NOT NULL,

    rate FLOAT NOT NULL,

    date_from DATE NOT NULL,

    FOREIGN KEY (user_id)
    REFERENCES users(id)
    ON DELETE CASCADE

);



-- =========================================
-- USERS TABLE
-- =========================================
CREATE TABLE users (
    id INT AUTO_INCREMENT PRIMARY KEY,

    email VARCHAR(255) NOT NULL UNIQUE,
    password VARCHAR(255) NOT NULL,

    phone VARCHAR(20),
    dairy_name VARCHAR(255),

    is_verified BOOLEAN DEFAULT FALSE,

    otp VARCHAR(10),
    otp_expiry DATETIME,

    reset_token VARCHAR(255),
    reset_token_expiry DATETIME,

    otp_code VARCHAR(6),
    otp_created_at DATETIME,

    security_password_hash VARCHAR(255),
    security_otp VARCHAR(6),
    security_otp_expiry DATETIME
);


-- =========================================
-- VENDORS TABLE
-- =========================================
CREATE TABLE vendors (

    id INT AUTO_INCREMENT PRIMARY KEY,

    vendor_id INT NOT NULL,

    name VARCHAR(100) NOT NULL,

    address TEXT,

    milk_type ENUM('cow','buffalo','both') DEFAULT 'cow',

    phone VARCHAR(15),

    user_id INT NOT NULL,

    FOREIGN KEY (user_id)
    REFERENCES users(id)
    ON DELETE CASCADE,

    UNIQUE KEY unique_vendor_per_user (vendor_id,user_id)

);


-- =========================================
-- MILK COLLECTION TABLE
-- =========================================
CREATE TABLE milk_collection (

    id INT AUTO_INCREMENT PRIMARY KEY,

    vendor_id INT,
    user_id INT,

    date DATE,

    slot ENUM('morning','evening') NOT NULL,

    milk_type ENUM('cow','buffalo') NOT NULL,

    quantity FLOAT NOT NULL,

    FOREIGN KEY (vendor_id,user_id)
    REFERENCES vendors(vendor_id,user_id)
    ON DELETE CASCADE,

    UNIQUE KEY unique_entry
    (vendor_id,user_id,date,slot,milk_type)

);


-- =========================================
-- ADVANCE TABLE
-- =========================================
CREATE TABLE advance (

    id INT AUTO_INCREMENT PRIMARY KEY,

    vendor_id INT,
    user_id INT,

    date DATE,

    amount FLOAT NOT NULL,

    FOREIGN KEY (vendor_id,user_id)
    REFERENCES vendors(vendor_id,user_id)
    ON DELETE CASCADE,

    UNIQUE KEY unique_advance
    (vendor_id,user_id,date)

);


-- =========================================
-- FOOD SACK RATE TABLE
-- =========================================
CREATE TABLE food_sack_rates (

    id INT AUTO_INCREMENT PRIMARY KEY,

    user_id INT NOT NULL,

    name VARCHAR(100) NOT NULL,

    rate FLOAT NOT NULL,

    date_from DATE NOT NULL,

    FOREIGN KEY (user_id)
    REFERENCES users(id)
    ON DELETE CASCADE

);


-- =========================================
-- FOOD SACK TABLE
-- =========================================
CREATE TABLE food_sack (

    id INT AUTO_INCREMENT PRIMARY KEY,

    vendor_id INT,
    user_id INT,

    date DATE,

    sack_qty INT NOT NULL,

    sack_rate_id INT NOT NULL,

    total_cost FLOAT NOT NULL,

    FOREIGN KEY (vendor_id,user_id)
    REFERENCES vendors(vendor_id,user_id)
    ON DELETE CASCADE,

    FOREIGN KEY (sack_rate_id)
    REFERENCES food_sack_rates(id)
    ON DELETE CASCADE,

    UNIQUE KEY unique_food
    (vendor_id,user_id,date,sack_rate_id)

);


-- =========================================
-- MILK RATE TABLE
-- =========================================
CREATE TABLE milk_rates (

    id INT AUTO_INCREMENT PRIMARY KEY,

    user_id INT NOT NULL,

    animal ENUM('cow','buffalo') NOT NULL,

    rate FLOAT NOT NULL,

    date_from DATE NOT NULL,

    FOREIGN KEY (user_id)
    REFERENCES users(id)
    ON DELETE CASCADE

);

CREATE TABLE staff (

    id INT AUTO_INCREMENT PRIMARY KEY,

    owner_id INT NOT NULL,

    name VARCHAR(100) NOT NULL,

    email VARCHAR(255) UNIQUE,

    password VARCHAR(255) NOT NULL,

    vehicle_number VARCHAR(20),

    role ENUM('driver','manager') DEFAULT 'driver',

    is_active BOOLEAN DEFAULT TRUE,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (owner_id)
    REFERENCES users(id)
    ON DELETE CASCADE

);


ALTER TABLE milk_collection
ADD COLUMN staff_id INT;


ALTER TABLE milk_collection
ADD CONSTRAINT fk_staff_milk
FOREIGN KEY (staff_id)
REFERENCES staff(id)
ON DELETE SET NULL;

CREATE TABLE vendor_milk_rates (

    id INT AUTO_INCREMENT PRIMARY KEY,

    vendor_id INT NOT NULL,
    user_id INT NOT NULL,

    cow_rate DECIMAL(6,2),
    buffalo_rate DECIMAL(6,2),

    date_from DATE NOT NULL,

    FOREIGN KEY (vendor_id,user_id)
    REFERENCES vendors(vendor_id,user_id)
    ON DELETE CASCADE

);

CREATE INDEX idx_milk_user_vendor_date
ON milk_collection(user_id,vendor_id,date);


CREATE INDEX idx_milk_user_date
ON milk_collection(user_id, date);

CREATE INDEX idx_advance_user_date
ON advance(user_id, date);

CREATE INDEX idx_food_user_date
ON food_sack(user_id, date);

ALTER TABLE food_sack
ADD COLUMN sack_rate DECIMAL(10,2);
ALTER TABLE food_sack_rates
ADD COLUMN is_active TINYINT(1) DEFAULT 1;


CREATE INDEX idx_sack_rate_user
ON food_sack_rates(user_id,is_active);


