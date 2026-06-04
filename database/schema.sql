IF OBJECT_ID('dbo.products', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.products (
        id NVARCHAR(100) NOT NULL PRIMARY KEY,
        name NVARCHAR(255) NOT NULL,
        price DECIMAL(10, 2) NOT NULL,
        currency NVARCHAR(10) NOT NULL CONSTRAINT DF_products_currency DEFAULT 'PLN',
        category NVARCHAR(100) NOT NULL,
        description NVARCHAR(MAX) NOT NULL,
        stock_status NVARCHAR(50) NOT NULL CONSTRAINT DF_products_stock_status DEFAULT 'unknown',
        image_url NVARCHAR(500) NULL,
        created_at DATETIME2 NOT NULL CONSTRAINT DF_products_created_at DEFAULT SYSUTCDATETIME()
    );
END;

IF OBJECT_ID('dbo.chat_sessions', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.chat_sessions (
        id NVARCHAR(64) NOT NULL PRIMARY KEY,
        user_id NVARCHAR(100) NULL,
        language NVARCHAR(10) NOT NULL,
        created_at DATETIME2 NOT NULL CONSTRAINT DF_chat_sessions_created_at DEFAULT SYSUTCDATETIME(),
        updated_at DATETIME2 NOT NULL CONSTRAINT DF_chat_sessions_updated_at DEFAULT SYSUTCDATETIME()
    );
END;

IF OBJECT_ID('dbo.chat_messages', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.chat_messages (
        id NVARCHAR(64) NOT NULL PRIMARY KEY,
        session_id NVARCHAR(64) NOT NULL,
        role NVARCHAR(20) NOT NULL,
        text NVARCHAR(MAX) NOT NULL,
        metadata NVARCHAR(MAX) NULL,
        created_at DATETIME2 NOT NULL CONSTRAINT DF_chat_messages_created_at DEFAULT SYSUTCDATETIME(),
        CONSTRAINT FK_chat_messages_sessions
            FOREIGN KEY (session_id) REFERENCES dbo.chat_sessions(id)
            ON DELETE CASCADE
    );
END;
