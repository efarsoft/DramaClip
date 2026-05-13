/**
 * 页面：剪辑编辑
 */

import React from 'react';
import { Card, Typography } from 'antd';

const { Title } = Typography;

const EditPage: React.FC = () => {
  return (
    <div style={{ padding: 24 }}>
      <div style={{ marginBottom: 24 }}>
        <Title level={2}>剪辑编辑</Title>
        <Typography.Text type="secondary">选择剪辑方案，编辑和调整片段</Typography.Text>
      </div>
      <Card>
        <Typography.Text>剪辑编辑功能开发中...</Typography.Text>
      </Card>
    </div>
  );
};

export default EditPage;
